from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw

from calibrate_chlorophyll import metric_block, solve_linear_system
from validate_chlorophyll import _draw_vertical_plot_label, _plot_count, _plot_font, _plot_metric


RESULTS_DIR = Path("outputs") / "results"
FOLDS = 5
HOLDOUT_FOLD = 0
BLOCK_SIZE_PIXELS = 1


def main() -> None:
    chlorophyll_report = calibrate_copernicus_chlorophyll()
    turbidity_report = calibrate_turbidity()
    print(f"Copernicus CHL calibration: {chlorophyll_report}")
    print(f"Turbidity calibration: {turbidity_report}")
    print("Reference values modified: False")


def calibrate_copernicus_chlorophyll() -> Path:
    directory = RESULTS_DIR / "chlorophyll_validation"
    source_report_path = latest_file(directory, "*copernicus*raster_validation.json")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    matchup_path = source_report_path.with_name(
        source_report_path.name.replace("_raster_validation.json", "_raster_matchups.csv")
    )
    rows = read_rows(
        matchup_path,
        "observed_reference_chlorophyll_a",
        "predicted_app_chlorophyll_a",
    )
    training, heldout = spatial_split(rows)
    coefficients = fit_quadratic(
        training,
        input_transform=math.log10,
        target_transform=math.log10,
    )
    observed = np.asarray([row[2] for row in heldout], dtype=np.float64)
    raw_app = np.asarray([row[3] for row in heldout], dtype=np.float64)
    calibrated = np.asarray(
        [
            min(7.0, max(0.01, 10 ** polynomial_value(math.log10(row[3]), coefficients)))
            for row in heldout
        ],
        dtype=np.float64,
    )
    heldout_metrics = metric_block(observed, calibrated)
    raw_metrics = metric_block(observed, raw_app)
    base_name = source_report_path.name.removesuffix("_raster_validation.json")
    plot_file = directory / f"{base_name}_copernicus_spatial_holdout_calibration.png"
    report_file = directory / f"{base_name}_copernicus_spatial_holdout_calibration.json"
    report = calibration_report(
        mode="copernicus_chl_spatial_holdout_calibration",
        source_report_path=source_report_path,
        source_report=source_report,
        matchup_path=matchup_path,
        coefficients=coefficients,
        training_count=len(training),
        heldout_metrics=heldout_metrics,
        raw_metrics=raw_metrics,
        plot_file=plot_file,
        model="quadratic regression in log10 CHL-A space",
    )
    write_calibration_plot(
        plot_file,
        observed,
        calibrated,
        title="Copernicus CHL-A Calibration - Spatial Holdout",
        subtitle="Held-out 4 km cells only; calibration applied to app values, reference unchanged",
        x_label="Copernicus reference CHL-A (mg/m3)",
        y_label="Calibrated app CHL-A (mg/m3)",
        reference_label="Copernicus Marine CHL, 2025-08-20",
        raw_metrics=raw_metrics,
        calibrated_metrics=heldout_metrics,
        axis_maximum=7.0,
        ticks=(0, 1, 2, 3, 4, 5, 6, 7),
        provisional=False,
    )
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_file


def calibrate_turbidity() -> Path:
    directory = RESULTS_DIR / "turbidity_validation"
    source_report_path = latest_file(directory, "*raster_validation.json")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    matchup_path = Path(str(source_report["matchup_csv"]))
    rows = read_rows(
        matchup_path,
        "reference_bbp_percentile_scaled",
        "app_turbidity_percentile_scaled",
    )
    training, heldout = spatial_split(rows)
    coefficients = fit_quadratic(training)
    observed = np.asarray([row[2] for row in heldout], dtype=np.float64)
    raw_app = np.asarray([row[3] for row in heldout], dtype=np.float64)
    calibrated = np.asarray(
        [min(1.0, max(0.0, polynomial_value(row[3], coefficients))) for row in heldout],
        dtype=np.float64,
    )
    heldout_metrics = metric_block(observed, calibrated)
    raw_metrics = metric_block(observed, raw_app)
    base_name = source_report_path.name.removesuffix("_raster_validation.json")
    plot_file = directory / f"{base_name}_turbidity_spatial_holdout_calibration.png"
    report_file = directory / f"{base_name}_turbidity_spatial_holdout_calibration.json"
    report = calibration_report(
        mode="turbidity_bbp_spatial_holdout_calibration",
        source_report_path=source_report_path,
        source_report=source_report,
        matchup_path=matchup_path,
        coefficients=coefficients,
        training_count=len(training),
        heldout_metrics=heldout_metrics,
        raw_metrics=raw_metrics,
        plot_file=plot_file,
        model="quadratic regression on percentile-scaled app and BBP proxy values",
    )
    report["interpretation"] = (
        "Provisional calibration: only 45 held-out 4 km cells and BBP is an indirect "
        "monthly turbidity proxy."
    )
    write_calibration_plot(
        plot_file,
        observed,
        calibrated,
        title="Turbidity vs Copernicus BBP - Spatial Holdout",
        subtitle="Held-out 4 km cells; percentile calibration applied to app values only",
        x_label="Copernicus BBP reference percentile (0-1)",
        y_label="Calibrated app turbidity percentile (0-1)",
        reference_label="Copernicus Marine monthly BBP proxy, 2025-08",
        raw_metrics=raw_metrics,
        calibrated_metrics=heldout_metrics,
        axis_maximum=1.0,
        ticks=(0, 0.25, 0.5, 0.75, 1.0),
        provisional=True,
    )
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_file


def latest_file(directory: Path, pattern: str) -> Path:
    candidates = list(directory.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No file matching {pattern} was found in {directory}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_rows(
    path: Path,
    reference_column: str,
    app_column: str,
) -> list[tuple[int, int, float, float]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            reference = float(row[reference_column])
            app_value = float(row[app_column])
            if not (math.isfinite(reference) and math.isfinite(app_value)):
                continue
            if reference < 0 or app_value < 0:
                continue
            rows.append(
                (
                    int(row["reference_pixel_x"]),
                    int(row["reference_pixel_y"]),
                    reference,
                    app_value,
                )
            )
    return rows


def spatial_split(
    rows: list[tuple[int, int, float, float]],
) -> tuple[list[tuple[int, int, float, float]], list[tuple[int, int, float, float]]]:
    training = []
    heldout = []
    for row in rows:
        fold = ((row[1] // BLOCK_SIZE_PIXELS) + (row[0] // BLOCK_SIZE_PIXELS)) % FOLDS
        (heldout if fold == HOLDOUT_FOLD else training).append(row)
    return training, heldout


def fit_quadratic(
    training: list[tuple[int, int, float, float]],
    input_transform: Callable[[float], float] | None = None,
    target_transform: Callable[[float], float] | None = None,
) -> list[float]:
    transform_x = input_transform or (lambda value: value)
    transform_y = target_transform or (lambda value: value)
    pairs = [
        (transform_x(row[3]), transform_y(row[2]))
        for row in training
        if row[2] > 0 and row[3] > 0
    ]
    power_sums = [sum(x**power for x, _y in pairs) for power in range(5)]
    targets = [sum((x**power) * y for x, y in pairs) for power in range(3)]
    matrix = [[power_sums[row + column] for column in range(3)] for row in range(3)]
    return solve_linear_system(matrix, targets)


def polynomial_value(value: float, coefficients: list[float]) -> float:
    return sum(coefficient * value**power for power, coefficient in enumerate(coefficients))


def calibration_report(
    *,
    mode: str,
    source_report_path: Path,
    source_report: dict[str, Any],
    matchup_path: Path,
    coefficients: list[float],
    training_count: int,
    heldout_metrics: dict[str, float | int],
    raw_metrics: dict[str, float | int],
    plot_file: Path,
    model: str,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "source_validation_report": str(source_report_path.resolve()),
        "reference_raster": source_report.get("reference_raster"),
        "matchup_csv": str(matchup_path.resolve()),
        "reference_values_modified": False,
        "app_values_calibrated": True,
        "model": model,
        "coefficients_c0_c1_c2": coefficients,
        "spatial_holdout": {
            "block_size_reference_pixels": BLOCK_SIZE_PIXELS,
            "folds": FOLDS,
            "holdout_fold": HOLDOUT_FOLD,
            "training_count": training_count,
            "heldout_count": heldout_metrics["count"],
            "rule": "((pixel_y // block_size) + (pixel_x // block_size)) % folds",
        },
        "heldout_metrics": heldout_metrics,
        "raw_heldout_metrics": raw_metrics,
        "raw_source_metrics": source_report.get("linear_metrics")
        or source_report.get("correlation_metrics"),
        "scatter_plot": str(plot_file.resolve()),
    }


def write_calibration_plot(
    output_file: Path,
    observed: np.ndarray,
    calibrated: np.ndarray,
    *,
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    reference_label: str,
    raw_metrics: dict[str, float | int],
    calibrated_metrics: dict[str, float | int],
    axis_maximum: float,
    ticks: tuple[float, ...],
    provisional: bool,
) -> None:
    width, height = 1400, 940
    plot_left, plot_top, plot_size = 150, 100, 720
    plot_right, plot_bottom = plot_left + plot_size, plot_top + plot_size
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font = _plot_font(30, False)
    subtitle_font = _plot_font(18, False)
    label_font = _plot_font(18, False)
    tick_font = _plot_font(14, False)
    section_font = _plot_font(17, False)
    body_font = _plot_font(15, False)
    footer_font = _plot_font(13, False)

    draw.text((plot_left, 28), title, fill="#17252b", font=title_font)
    draw.text((plot_left, 67), subtitle, fill="#40535c", font=subtitle_font)
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), fill="#fbfcfd", outline="#1f292e", width=2)

    def position(value: float) -> int:
        return int(round(value * plot_size / axis_maximum))

    for tick in ticks:
        x = plot_left + position(tick)
        y = plot_bottom - position(tick)
        draw.line((x, plot_top, x, plot_bottom), fill="#d6dde0", width=1)
        draw.line((plot_left, y, plot_right, y), fill="#d6dde0", width=1)
        label = f"{tick:g}"
        box = draw.textbbox((0, 0), label, font=tick_font)
        label_width, label_height = box[2] - box[0], box[3] - box[1]
        draw.text((x - label_width / 2, plot_bottom + 12), label, fill="#1f292e", font=tick_font)
        draw.text((plot_left - label_width - 14, y - label_height / 2 - 2), label, fill="#1f292e", font=tick_font)

    draw.line((plot_left, plot_bottom, plot_right, plot_top), fill="#3d464b", width=2)
    for reference, app_value in zip(observed, calibrated):
        if not (0 <= reference <= axis_maximum and 0 <= app_value <= axis_maximum):
            continue
        x = plot_left + position(float(reference))
        y = plot_bottom - position(float(app_value))
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#1674b8", outline="#0b4f78", width=1)
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline="#1f292e", width=2)

    x_box = draw.textbbox((0, 0), x_label, font=label_font)
    draw.text((plot_left + (plot_size - (x_box[2] - x_box[0])) / 2, 865), x_label, fill="#17252b", font=label_font)
    _draw_vertical_plot_label(image, y_label, 36, plot_top + plot_size // 2, label_font)

    info_left, info_top, info_right, info_bottom = 920, 100, 1260, 615
    draw.rectangle((info_left, info_top, info_right, info_bottom), fill="#f7f9fa", outline="#aeb9be", width=1)
    sections = (
        ("Held-out calibrated result", calibrated_metrics),
        ("Raw held-out comparison", raw_metrics),
    )
    info_y = info_top + 20
    for index, (heading, metrics) in enumerate(sections):
        if index:
            info_y += 20
        draw.text((info_left + 20, info_y), heading, fill="#18252b", font=section_font)
        info_y += 32
        for line in (
            f"n = {_plot_count(metrics.get('count'))}",
            f"Bias = {_plot_metric(metrics.get('bias'))}",
            f"RMSE = {_plot_metric(metrics.get('rmse'))}",
            f"r = {_plot_metric(metrics.get('pearson_r'), 3)}",
        ):
            draw.text((info_left + 20, info_y), line, fill="#18252b", font=body_font)
            info_y += 25
    info_y += 20
    heading = "Reference handling"
    draw.text((info_left + 20, info_y), heading, fill="#18252b", font=section_font)
    info_y += 34
    handling = ["Reference values unchanged", "Calibration applied to app only", "20% spatial cells held out"]
    if provisional:
        handling.append("Provisional proxy result")
    for line in handling:
        draw.text((info_left + 20, info_y), line, fill="#40535c", font=body_font)
        info_y += 25

    draw.text((plot_left, 910), f"Reference: {reference_label} | Raw reference unchanged", fill="#40535c", font=footer_font)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_file, format="PNG", compress_level=6)


if __name__ == "__main__":
    main()
