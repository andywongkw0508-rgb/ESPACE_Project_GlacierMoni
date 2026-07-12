from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from validate_chlorophyll import write_hls_scatter_plot


DEFAULT_VALIDATION_DIR = Path("outputs") / "results" / "chlorophyll_validation"


def main() -> None:
    args = parse_args()
    report_path = Path(args.report) if args.report else latest_hls_report(Path(args.validation_dir))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    matchup_path = report_path.with_name(
        report_path.name.replace("_raster_validation.json", "_raster_matchups.csv")
    )
    samples, stride = read_matchup_sample(
        matchup_path,
        int(report["matchup_count"]),
        max_sample=args.max_sample,
    )
    training, heldout = spatial_split(
        samples,
        block_size=args.block_size,
        folds=args.folds,
        holdout_fold=args.holdout_fold,
    )
    if len(training) < 100 or len(heldout) < 100:
        raise RuntimeError("The spatial split did not produce enough calibration samples.")

    coefficients = fit_log_polynomial(training, degree=2)
    heldout_reference = np.asarray([sample[2] for sample in heldout], dtype=np.float64)
    heldout_raw_app = np.asarray([10 ** sample[0] for sample in heldout], dtype=np.float64)
    heldout_calibrated = np.asarray(
        [calibrated_value(sample[0], coefficients) for sample in heldout],
        dtype=np.float64,
    )
    heldout_metrics = metric_block(heldout_reference, heldout_calibrated)
    raw_heldout_metrics = metric_block(heldout_reference, heldout_raw_app)

    base_name = report_path.name.removesuffix("_raster_validation.json")
    output_dir = report_path.parent
    plot_file = output_dir / f"{base_name}_hls_spatial_holdout_calibration.png"
    output_report = output_dir / f"{base_name}_hls_spatial_holdout_calibration.json"
    calibration_report: dict[str, Any] = {
        "mode": "hls_spatial_holdout_calibration",
        "source_validation_report": str(report_path.resolve()),
        "reference_raster": report.get("reference_raster"),
        "matchup_csv": str(matchup_path.resolve()),
        "analysis_filter": "0 < HLS-derived CHL-A <= 10 mg/m3 and app CHL-A > 0",
        "reference_values_modified": False,
        "app_values_calibrated": True,
        "model": "quadratic regression in log10 space",
        "model_formula": "log10(HLS CHL-A) = c0 + c1*x + c2*x^2; x=log10(app CHL-A)",
        "coefficients_c0_c1_c2": coefficients,
        "sampling": {
            "rule": f"every {stride}th matchup row before quality filtering",
            "sample_count": len(samples),
            "training_count": len(training),
            "heldout_count": len(heldout),
        },
        "spatial_holdout": {
            "block_size_reference_pixels": args.block_size,
            "folds": args.folds,
            "holdout_fold": args.holdout_fold,
            "rule": "((pixel_y // block_size) + (pixel_x // block_size)) % folds",
        },
        "heldout_metrics": heldout_metrics,
        "raw_qualified_metrics": raw_heldout_metrics,
        "raw_full_validation_metrics": report.get("linear_metrics", {}),
        "raw_reference_modified": False,
        "scatter_plot": str(plot_file.resolve()),
    }
    write_hls_scatter_plot(
        plot_file,
        heldout_reference,
        heldout_calibrated,
        calibration_report,
        Path(str(report.get("reference_raster", "HLS S30"))).stem,
    )
    output_report.write_text(json.dumps(calibration_report, indent=2), encoding="utf-8")
    print(f"Calibration report: {output_report}")
    print(f"Calibration plot: {plot_file}")
    print(f"Held-out Pearson r: {heldout_metrics['pearson_r']:.3f}")
    print(f"Held-out RMSE: {heldout_metrics['rmse']:.3f} mg/m3")
    print("Reference values modified: False")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate app CHL-A against unchanged HLS-derived CHL-A using spatial "
            "training and holdout blocks."
        )
    )
    parser.add_argument("--report", help="HLS raster-validation JSON. Defaults to the latest report.")
    parser.add_argument("--validation-dir", default=str(DEFAULT_VALIDATION_DIR))
    parser.add_argument("--max-sample", type=int, default=240_000)
    parser.add_argument("--block-size", type=int, default=64)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--holdout-fold", type=int, default=0)
    return parser.parse_args()


def latest_hls_report(directory: Path) -> Path:
    candidates = list(directory.glob("*HLS*raster_validation.json"))
    if not candidates:
        raise FileNotFoundError(f"No HLS validation report found in {directory}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_matchup_sample(
    path: Path,
    matchup_count: int,
    max_sample: int,
) -> tuple[list[tuple[float, float, float, int, int]], int]:
    stride = max(1, int(math.ceil(matchup_count / max(1, max_sample))))
    samples: list[tuple[float, float, float, int, int]] = []
    with path.open("r", encoding="utf-8") as handle:
        header = next(handle).strip().split(",")
        indexes = {name: index for index, name in enumerate(header)}
        required = (
            "reference_pixel_x",
            "reference_pixel_y",
            "observed_reference_chlorophyll_a",
            "predicted_app_chlorophyll_a",
        )
        missing = [name for name in required if name not in indexes]
        if missing:
            raise ValueError(f"Missing matchup columns: {', '.join(missing)}")
        for row_index, line in enumerate(handle):
            if row_index % stride:
                continue
            values = line.rstrip().split(",")
            reference = float(values[indexes["observed_reference_chlorophyll_a"]])
            app_value = float(values[indexes["predicted_app_chlorophyll_a"]])
            if not (0 < reference <= 10.0 and app_value > 0):
                continue
            pixel_x = int(values[indexes["reference_pixel_x"]])
            pixel_y = int(values[indexes["reference_pixel_y"]])
            samples.append(
                (math.log10(app_value), math.log10(reference), reference, pixel_x, pixel_y)
            )
    return samples, stride


def spatial_split(
    samples: list[tuple[float, float, float, int, int]],
    block_size: int,
    folds: int,
    holdout_fold: int,
) -> tuple[list[tuple[float, float, float, int, int]], list[tuple[float, float, float, int, int]]]:
    if block_size < 1 or folds < 2 or not 0 <= holdout_fold < folds:
        raise ValueError("Use block-size >= 1, folds >= 2, and a valid holdout-fold.")
    training = []
    heldout = []
    for sample in samples:
        fold = ((sample[4] // block_size) + (sample[3] // block_size)) % folds
        (heldout if fold == holdout_fold else training).append(sample)
    return training, heldout


def fit_log_polynomial(
    training: list[tuple[float, float, float, int, int]],
    degree: int,
) -> list[float]:
    power_sums = [sum(sample[0] ** power for sample in training) for power in range(2 * degree + 1)]
    targets = [
        sum((sample[0] ** power) * sample[1] for sample in training)
        for power in range(degree + 1)
    ]
    matrix = [
        [power_sums[row + column] for column in range(degree + 1)]
        for row in range(degree + 1)
    ]
    return solve_linear_system(matrix, targets)


def solve_linear_system(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    augmented = [list(matrix[row]) + [target[row]] for row in range(size)]
    for pivot_column in range(size):
        pivot_row = max(
            range(pivot_column, size),
            key=lambda row: abs(augmented[row][pivot_column]),
        )
        augmented[pivot_column], augmented[pivot_row] = (
            augmented[pivot_row],
            augmented[pivot_column],
        )
        pivot = augmented[pivot_column][pivot_column]
        if abs(pivot) < 1e-15:
            raise RuntimeError("The calibration system is singular.")
        for column in range(pivot_column, size + 1):
            augmented[pivot_column][column] /= pivot
        for row in range(size):
            if row == pivot_column:
                continue
            scale = augmented[row][pivot_column]
            for column in range(pivot_column, size + 1):
                augmented[row][column] -= scale * augmented[pivot_column][column]
    return [augmented[row][size] for row in range(size)]


def calibrated_value(log_app_value: float, coefficients: list[float]) -> float:
    log_value = sum(
        coefficient * (log_app_value ** power)
        for power, coefficient in enumerate(coefficients)
    )
    return min(10.0, max(0.05, 10 ** log_value))


def metric_block(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    residual = predicted - observed
    observed_centered = observed - float(np.mean(observed))
    predicted_centered = predicted - float(np.mean(predicted))
    denominator = math.sqrt(
        float(np.sum(observed_centered**2) * np.sum(predicted_centered**2))
    )
    total_variance = float(np.sum(observed_centered**2))
    return {
        "count": int(observed.size),
        "observed_mean": float(np.mean(observed)),
        "predicted_mean": float(np.mean(predicted)),
        "bias": float(np.mean(residual)),
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "r2": float(1.0 - np.sum(residual**2) / total_variance),
        "pearson_r": float(np.sum(observed_centered * predicted_centered) / denominator),
    }


if __name__ == "__main__":
    main()
