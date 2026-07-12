from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("outputs") / "results" / "chlorophyll_validation"


@dataclass
class SampleResult:
    source_row: dict[str, str]
    raster_x: int
    raster_y: int
    observed: float
    predicted: float

    @property
    def residual(self) -> float:
        return self.predicted - self.observed


@dataclass
class RasterMatchup:
    pixel_x: int
    pixel_y: int
    x: float
    y: float
    observed: float
    predicted: float

    @property
    def residual(self) -> float:
        return self.predicted - self.observed


@dataclass
class SkipCounts:
    invalid_observation: int = 0
    transform_failed: int = 0
    outside_raster: int = 0
    nodata_or_invalid_raster: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "invalid_observation": self.invalid_observation,
            "transform_failed": self.transform_failed,
            "outside_raster": self.outside_raster,
            "nodata_or_invalid_raster": self.nodata_or_invalid_raster,
        }


def main() -> None:
    args = parse_args()
    raster = Path(args.raster)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.reference_raster:
        reference_raster = Path(args.reference_raster)
        summary, matchup_file, summary_file = validate_reference_raster(
            raster,
            reference_raster,
            output_dir,
            resampling=args.resampling,
        )
        print_summary(summary, matchup_file, summary_file)
        return

    if not args.observations:
        raise ValueError("Provide either --observations or --reference-raster.")

    observations = Path(args.observations)
    samples, skipped = build_matchups(
        raster,
        observations,
        x_column=args.x_column,
        y_column=args.y_column,
        observed_column=args.observed_column,
        observation_crs=args.observation_crs,
        window_size=args.window_size,
    )
    if not samples:
        raise RuntimeError(
            "No valid chlorophyll-a matchups were found. Check the CSV columns, CRS, and raster overlap."
        )

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    matchup_file = output_dir / f"{raster.stem}_chlorophyll_matchups_{timestamp}.csv"
    summary_file = output_dir / f"{raster.stem}_chlorophyll_validation_{timestamp}.json"
    write_matchup_csv(matchup_file, samples)
    summary = validation_summary(samples, skipped, raster, observations)
    write_summary_json(summary_file, summary)
    print_summary(summary, matchup_file, summary_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an application-generated CHL-A GeoTIFF against reference/in-situ "
            "chlorophyll-a observations or a reference CHL-A raster."
        )
    )
    parser.add_argument("--raster", required=True, help="CHL_A GeoTIFF produced by the application.")
    parser.add_argument("--observations", help="CSV with point observations.")
    parser.add_argument(
        "--reference-raster",
        help=(
            "Reference CHL-A raster/map to compare against. The application raster is "
            "resampled to this grid before metrics are computed."
        ),
    )
    parser.add_argument(
        "--resampling",
        choices=["average", "bilinear", "nearest"],
        default="average",
        help="Resampling used when matching the application raster to --reference-raster. Default: average",
    )
    parser.add_argument("--x-column", default="lon", help="Observation x/longitude column. Default: lon")
    parser.add_argument("--y-column", default="lat", help="Observation y/latitude column. Default: lat")
    parser.add_argument(
        "--observed-column",
        default="chlorophyll_a",
        help="Reference chlorophyll-a column in mg/m3. Default: chlorophyll_a",
    )
    parser.add_argument(
        "--observation-crs",
        default="EPSG:4326",
        help="CRS of the observation coordinates. Default: EPSG:4326",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=1,
        help="Odd pixel window size to average around each observation. Default: 1",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Folder for validation outputs. Default: {DEFAULT_OUTPUT_DIR}",
    )
    return parser.parse_args()


def build_matchups(
    raster_path: Path,
    observation_path: Path,
    x_column: str,
    y_column: str,
    observed_column: str,
    observation_crs: str,
    window_size: int,
) -> tuple[list[SampleResult], SkipCounts]:
    gdal, _osr = require_gdal()
    gdal.UseExceptions()
    if window_size < 1:
        raise ValueError("--window-size must be at least 1.")
    if window_size % 2 == 0:
        raise ValueError("--window-size must be odd, for example 1, 3, or 5.")

    dataset = gdal.Open(str(raster_path))
    if dataset is None:
        raise RuntimeError(f"Could not open CHL-A raster: {raster_path}")
    band = dataset.GetRasterBand(1)
    raster_array = band.ReadAsArray().astype(np.float64)
    nodata = band.GetNoDataValue()
    inverse_transform = gdal.InvGeoTransform(dataset.GetGeoTransform())
    transformer = observation_to_raster_transform(observation_crs, dataset.GetProjection())

    samples: list[SampleResult] = []
    skipped = SkipCounts()
    with observation_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        require_columns(reader.fieldnames or [], [x_column, y_column, observed_column])
        for row in reader:
            observed = parse_float(row.get(observed_column, ""))
            x_value = parse_float(row.get(x_column, ""))
            y_value = parse_float(row.get(y_column, ""))
            if observed is None or x_value is None or y_value is None or observed <= 0:
                skipped.invalid_observation += 1
                continue
            try:
                raster_x_geo, raster_y_geo, _z = transformer.TransformPoint(float(x_value), float(y_value))
            except Exception:
                skipped.transform_failed += 1
                continue
            px_float, py_float = apply_inverse_geotransform(inverse_transform, raster_x_geo, raster_y_geo)
            px = int(math.floor(px_float))
            py = int(math.floor(py_float))
            if px < 0 or py < 0 or px >= dataset.RasterXSize or py >= dataset.RasterYSize:
                skipped.outside_raster += 1
                continue
            predicted = sample_raster_window(raster_array, px, py, window_size, nodata)
            if predicted is None or predicted <= 0:
                skipped.nodata_or_invalid_raster += 1
                continue
            samples.append(
                SampleResult(
                    source_row=dict(row),
                    raster_x=px,
                    raster_y=py,
                    observed=observed,
                    predicted=predicted,
                )
            )
    dataset = None
    return samples, skipped


def validate_reference_raster(
    raster_path: Path,
    reference_raster_path: Path,
    output_dir: Path,
    resampling: str,
) -> tuple[dict[str, Any], Path, Path]:
    gdal, _osr = require_gdal()
    gdal.UseExceptions()

    source_dataset = gdal.Open(str(raster_path))
    if source_dataset is None:
        raise RuntimeError(f"Could not open CHL-A raster: {raster_path}")
    reference_dataset = gdal.Open(str(reference_raster_path))
    if reference_dataset is None:
        raise RuntimeError(f"Could not open reference raster: {reference_raster_path}")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base_name = f"{raster_path.stem}_vs_{reference_raster_path.stem}_{timestamp}"
    resampled_file = output_dir / f"{base_name}_app_resampled_to_reference.tif"
    matchup_file = output_dir / f"{base_name}_raster_matchups.csv"
    summary_file = output_dir / f"{base_name}_raster_validation.json"

    source_nodata = source_dataset.GetRasterBand(1).GetNoDataValue()
    reference_projection = reference_dataset.GetProjection()
    reference_bounds = dataset_bounds(reference_dataset)
    warp_options = {
        "format": "GTiff",
        "dstSRS": reference_projection or None,
        "outputBounds": reference_bounds,
        "width": reference_dataset.RasterXSize,
        "height": reference_dataset.RasterYSize,
        "resampleAlg": resampling_algorithm(gdal, resampling),
        "dstNodata": -9999.0,
        "creationOptions": ["COMPRESS=LZW", "TILED=YES"],
        "multithread": True,
    }
    if source_nodata is not None:
        warp_options["srcNodata"] = float(source_nodata)

    resampled_dataset = gdal.Warp(str(resampled_file), source_dataset, options=gdal.WarpOptions(**warp_options))
    if resampled_dataset is None:
        raise RuntimeError("GDAL could not resample the application CHL-A raster to the reference grid.")
    resampled_dataset.FlushCache()

    reference_band = reference_dataset.GetRasterBand(1)
    predicted_band = resampled_dataset.GetRasterBand(1)
    reference_array = reference_band.ReadAsArray().astype(np.float64)
    predicted_array = predicted_band.ReadAsArray().astype(np.float64)
    reference_nodata = reference_band.GetNoDataValue()
    predicted_nodata = predicted_band.GetNoDataValue()

    reference_valid = valid_chlorophyll_mask(reference_array, reference_nodata)
    predicted_valid = valid_chlorophyll_mask(predicted_array, predicted_nodata)
    paired_mask = reference_valid & predicted_valid
    if not paired_mask.any():
        raise RuntimeError("No valid overlapping CHL-A cells were found between the app raster and reference raster.")

    matchups = raster_matchups_from_arrays(reference_array, predicted_array, paired_mask, reference_dataset.GetGeoTransform())
    write_raster_matchup_csv(matchup_file, matchups)

    observed = reference_array[paired_mask]
    predicted = predicted_array[paired_mask]
    residual = predicted - observed
    summary: dict[str, Any] = {
        "mode": "reference_raster",
        "raster": str(raster_path),
        "reference_raster": str(reference_raster_path),
        "resampled_raster": str(resampled_file),
        "resampling": resampling,
        "matchup_count": int(paired_mask.sum()),
        "reference_valid_cells": int(reference_valid.sum()),
        "predicted_valid_cells": int(predicted_valid.sum()),
        "skipped": {
            "reference_nodata_or_invalid": int(reference_array.size - reference_valid.sum()),
            "predicted_nodata_or_invalid": int(reference_valid.sum() - paired_mask.sum()),
        },
        "linear_metrics": metric_block(observed, predicted, residual),
        "reference_statistics": array_statistics(reference_array, reference_nodata),
        "predicted_statistics_on_reference_grid": array_statistics(predicted_array, predicted_nodata),
    }

    positive = (observed > 0) & (predicted > 0)
    if np.count_nonzero(positive) >= 2:
        observed_log = np.log10(observed[positive])
        predicted_log = np.log10(predicted[positive])
        summary["log10_metrics"] = metric_block(
            observed_log,
            predicted_log,
            predicted_log - observed_log,
        )

    if "hls" in reference_raster_path.name.lower():
        summary["range_limited_metrics"] = {
            "reference_chl_a_le_30_mg_m3": range_limited_metric_block(
                observed,
                predicted,
                maximum_reference=30.0,
            ),
            "reference_chl_a_le_10_mg_m3": range_limited_metric_block(
                observed,
                predicted,
                maximum_reference=10.0,
            ),
        }
        scatter_file = output_dir / f"{base_name}_hls_scatter_log.png"
        write_hls_scatter_plot(
            scatter_file,
            observed,
            predicted,
            summary,
            reference_raster_path.stem,
        )
        summary["scatter_plot_log"] = str(scatter_file.resolve())
        summary["scatter_plot_layout_version"] = 3
        summary["quality_control"] = {
            "primary_plot_filter": (
                "0 < HLS-derived CHL-A <= 10 mg/m3 and app CHL-A > 0"
            ),
            "reference_values_modified": False,
            "full_overlap_metrics_retained": True,
        }

    write_summary_json(summary_file, summary)
    source_dataset = None
    reference_dataset = None
    resampled_dataset = None
    return summary, matchup_file, summary_file


def resampling_algorithm(gdal: Any, name: str) -> int:
    return {
        "average": gdal.GRA_Average,
        "bilinear": gdal.GRA_Bilinear,
        "nearest": gdal.GRA_NearestNeighbour,
    }[name]


def dataset_bounds(dataset: Any) -> tuple[float, float, float, float]:
    gt = dataset.GetGeoTransform()
    width = dataset.RasterXSize
    height = dataset.RasterYSize
    corners = [
        apply_geotransform(gt, 0, 0),
        apply_geotransform(gt, width, 0),
        apply_geotransform(gt, 0, height),
        apply_geotransform(gt, width, height),
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return min(xs), min(ys), max(xs), max(ys)


def apply_geotransform(geotransform: tuple[float, ...], px: float, py: float) -> tuple[float, float]:
    x = geotransform[0] + geotransform[1] * px + geotransform[2] * py
    y = geotransform[3] + geotransform[4] * px + geotransform[5] * py
    return x, y


def valid_chlorophyll_mask(array: np.ndarray, nodata: float | None) -> np.ndarray:
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= ~np.isclose(array, float(nodata))
    valid &= array > 0
    return valid


def raster_matchups_from_arrays(
    observed: np.ndarray,
    predicted: np.ndarray,
    mask: np.ndarray,
    geotransform: tuple[float, ...],
) -> list[RasterMatchup]:
    rows, columns = np.where(mask)
    matchups: list[RasterMatchup] = []
    for py, px in zip(rows, columns):
        x, y = apply_geotransform(geotransform, px + 0.5, py + 0.5)
        matchups.append(
            RasterMatchup(
                pixel_x=int(px),
                pixel_y=int(py),
                x=float(x),
                y=float(y),
                observed=float(observed[py, px]),
                predicted=float(predicted[py, px]),
            )
        )
    return matchups


def array_statistics(array: np.ndarray, nodata: float | None) -> dict[str, float | int | None]:
    valid = valid_chlorophyll_mask(array, nodata)
    if not valid.any():
        return {"valid_count": 0, "min": None, "max": None, "mean": None, "median": None}
    values = array[valid]
    return {
        "valid_count": int(values.size),
        "min": finite_float(np.min(values)),
        "max": finite_float(np.max(values)),
        "mean": finite_float(np.mean(values)),
        "median": finite_float(np.median(values)),
    }


def range_limited_metric_block(
    observed: np.ndarray,
    predicted: np.ndarray,
    maximum_reference: float,
) -> dict[str, float | int | None]:
    selected = (
        np.isfinite(observed)
        & np.isfinite(predicted)
        & (observed > 0)
        & (observed <= maximum_reference)
        & (predicted > 0)
    )
    count = int(np.count_nonzero(selected))
    if count < 2:
        return {"count": count}
    selected_observed = observed[selected]
    selected_predicted = predicted[selected]
    metrics: dict[str, float | int | None] = {
        "count": count,
        "observed_median": finite_float(np.median(selected_observed)),
        "predicted_median": finite_float(np.median(selected_predicted)),
    }
    metrics.update(
        metric_block(
            selected_observed,
            selected_predicted,
            selected_predicted - selected_observed,
        )
    )
    return metrics


def write_hls_scatter_plot(
    output_file: Path,
    observed: np.ndarray,
    predicted: np.ndarray,
    summary: dict[str, Any],
    reference_name: str,
) -> None:
    from PIL import Image, ImageDraw

    calibration_mode = summary.get("mode") == "hls_spatial_holdout_calibration"
    valid = (
        np.isfinite(observed)
        & np.isfinite(predicted)
        & (observed > 0)
        & (predicted > 0)
    )
    qualified = valid & (observed <= 10.0)
    plot_observed = observed[qualified]
    plot_predicted = predicted[qualified]
    if plot_observed.size == 0:
        raise RuntimeError("No HLS CHL-A matchups pass the <=10 mg/m3 analysis filter.")
    max_points = 180_000
    stride = max(1, int(math.ceil(plot_observed.size / max_points)))
    plot_observed = plot_observed[::stride]
    plot_predicted = plot_predicted[::stride]
    width, height = 1400, 940
    plot_left, plot_top, plot_size = 150, 100, 720
    plot_right = plot_left + plot_size
    plot_bottom = plot_top + plot_size
    log_min = math.log10(0.05)
    plot_maximum = 10.0
    log_max = math.log10(plot_maximum)
    log_span = log_max - log_min

    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font = _plot_font(30, bold=False)
    subtitle_font = _plot_font(18, bold=False)
    label_font = _plot_font(18, bold=False)
    tick_font = _plot_font(14, bold=False)
    body_font = _plot_font(15, bold=False)
    section_font = _plot_font(17, bold=False)
    footer_font = _plot_font(13, bold=False)

    title = (
        "HLS-Calibrated CHL-A - Spatial Holdout"
        if calibration_mode
        else "HLS S30 30 m CHL-A Validation"
    )
    subtitle = (
        "Held-out spatial blocks only; calibration applied to app values, reference unchanged"
        if calibration_mode
        else "Qualified comparison: matched positive pixels with HLS-derived CHL-A <= 10 mg/m3"
    )
    draw.text((plot_left, 28), title, fill="#17252b", font=title_font)
    draw.text(
        (plot_left, 67),
        subtitle,
        fill="#40535c",
        font=subtitle_font,
    )
    draw.rectangle(
        (plot_left, plot_top, plot_right, plot_bottom),
        fill="#fbfcfd",
        outline="#1f292e",
        width=2,
    )

    ticks = (0.1, 0.3, 1, 3, 10)
    tick_labels = ("0.1", "0.3", "1", "3", "10")

    def x_position(value: float) -> int:
        return int(round(plot_left + (math.log10(value) - log_min) * plot_size / log_span))

    def y_position(value: float) -> int:
        return int(round(plot_bottom - (math.log10(value) - log_min) * plot_size / log_span))

    for value, label in zip(ticks, tick_labels):
        x = x_position(value)
        y = y_position(value)
        draw.line((x, plot_top, x, plot_bottom), fill="#d6dde0", width=1)
        draw.line((plot_left, y, plot_right, y), fill="#d6dde0", width=1)
        tick_box = draw.textbbox((0, 0), label, font=tick_font)
        tick_width = tick_box[2] - tick_box[0]
        tick_height = tick_box[3] - tick_box[1]
        draw.text((x - tick_width / 2, plot_bottom + 12), label, fill="#1f292e", font=tick_font)
        draw.text(
            (plot_left - tick_width - 14, y - tick_height / 2 - 2),
            label,
            fill="#1f292e",
            font=tick_font,
        )

    inside = (
        (plot_observed >= 0.05)
        & (plot_observed <= plot_maximum)
        & (plot_predicted >= 0.05)
        & (plot_predicted <= plot_maximum)
    )
    if np.any(inside):
        x_values = np.log10(plot_observed[inside])
        y_values = np.log10(plot_predicted[inside])
        x_pixels = np.rint(plot_left + (x_values - log_min) * plot_size / log_span).astype(np.int32)
        y_pixels = np.rint(plot_bottom - (y_values - log_min) * plot_size / log_span).astype(np.int32)
        scatter = np.zeros((height, width, 4), dtype=np.uint8)
        scatter[y_pixels, x_pixels] = (22, 116, 184, 120)
        image = Image.alpha_composite(image, Image.fromarray(scatter))
        draw = ImageDraw.Draw(image)

    draw.line(
        (
            x_position(0.05),
            y_position(0.05),
            x_position(plot_maximum),
            y_position(plot_maximum),
        ),
        fill="#3d464b",
        width=2,
    )
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline="#1f292e", width=2)
    x_label = "HLS-derived CHL-A reference (mg/m3, log scale)"
    x_label_box = draw.textbbox((0, 0), x_label, font=label_font)
    x_label_width = x_label_box[2] - x_label_box[0]
    draw.text(
        (plot_left + (plot_size - x_label_width) / 2, 865),
        x_label,
        fill="#17252b",
        font=label_font,
    )
    _draw_vertical_plot_label(
        image,
        (
            "Calibrated app CHL-A (mg/m3, log scale)"
            if calibration_mode
            else "App CHL-A (mg/m3, log scale)"
        ),
        x=36,
        center_y=plot_top + plot_size // 2,
        font=label_font,
    )

    info_left, info_top, info_right, info_bottom = 920, 100, 1260, 615
    draw.rectangle(
        (info_left, info_top, info_right, info_bottom),
        fill="#f7f9fa",
        outline="#aeb9be",
        width=1,
    )
    if calibration_mode:
        heldout = summary.get("heldout_metrics", {})
        raw_qualified = summary.get("raw_qualified_metrics", {})
        sections = (
            ("Held-out calibrated result", heldout, heldout.get("count")),
            ("Raw qualified comparison", raw_qualified, raw_qualified.get("count")),
        )
        handling_lines = (
            "HLS reference unchanged",
            "Calibration applied to app only",
            "20% spatial blocks held out",
        )
    else:
        linear = summary.get("linear_metrics", {})
        ranges = summary.get("range_limited_metrics", {})
        range_10 = ranges.get("reference_chl_a_le_10_mg_m3", {})
        sections = (
            ("Qualified: HLS <= 10 mg/m3", range_10, range_10.get("count")),
            ("Full overlap (audit result)", linear, summary.get("matchup_count")),
        )
        handling_lines = (
            "Raw HLS values unchanged",
            "Filter applied to analysis only",
            "Full metrics retained in report",
        )
    info_y = info_top + 20
    for section_index, (heading, metrics, count) in enumerate(sections):
        if section_index:
            info_y += 20
        draw.text((info_left + 20, info_y), heading, fill="#18252b", font=section_font)
        info_y += 32
        for line in (
            f"n = {_plot_count(count)}",
            f"Bias = {_plot_metric(metrics.get('bias'))} mg/m3",
            f"RMSE = {_plot_metric(metrics.get('rmse'))} mg/m3",
            f"r = {_plot_metric(metrics.get('pearson_r'), 3)}",
        ):
            draw.text((info_left + 20, info_y), line, fill="#18252b", font=body_font)
            info_y += 25

    info_y += 20
    draw.text((info_left + 20, info_y), "Reference handling", fill="#18252b", font=section_font)
    info_y += 34
    for line in handling_lines:
        draw.text((info_left + 20, info_y), line, fill="#40535c", font=body_font)
        info_y += 25

    draw.text(
        (plot_left, 910),
        f"Reference source: NASA HLS S30 {reference_name} | Raw reference unchanged",
        fill="#40535c",
        font=footer_font,
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_file, format="PNG", compress_level=6)


def _plot_font(size: int, bold: bool) -> Any:
    from PIL import ImageFont

    candidates = (
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _draw_vertical_plot_label(
    image: Any,
    text: str,
    x: int,
    center_y: int,
    font: Any,
) -> None:
    from PIL import Image, ImageDraw

    box = ImageDraw.Draw(image).textbbox((0, 0), text, font=font)
    label_width = box[2] - box[0]
    label_height = box[3] - box[1]
    label = Image.new("RGBA", (label_width + 8, label_height + 8), (255, 255, 255, 0))
    ImageDraw.Draw(label).text((4, 2), text, fill="#17252b", font=font)
    rotated = label.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(rotated, (x, int(center_y - rotated.height / 2)))


def _plot_metric(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.{digits}f}" if math.isfinite(number) else "--"


def _plot_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "--"


def observation_to_raster_transform(observation_crs: str, raster_projection: str) -> Any:
    _gdal, osr = require_gdal()
    source = osr.SpatialReference()
    source.SetFromUserInput(observation_crs)
    target = osr.SpatialReference()
    if raster_projection:
        target.ImportFromWkt(raster_projection)
    else:
        target.SetFromUserInput(observation_crs)
    if hasattr(osr, "OAMS_TRADITIONAL_GIS_ORDER"):
        source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(source, target)


def require_gdal() -> tuple[Any, Any]:
    try:
        from osgeo import gdal, osr
    except ImportError as exc:
        raise RuntimeError(
            "GDAL Python bindings are required to sample the CHL-A raster. "
            "Run this script inside the glacier-monitoring conda environment."
        ) from exc
    return gdal, osr


def apply_inverse_geotransform(inverse_transform: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    px = inverse_transform[0] + inverse_transform[1] * x + inverse_transform[2] * y
    py = inverse_transform[3] + inverse_transform[4] * x + inverse_transform[5] * y
    return px, py


def sample_raster_window(
    array: np.ndarray,
    px: int,
    py: int,
    window_size: int,
    nodata: float | None,
) -> float | None:
    radius = window_size // 2
    y0 = max(0, py - radius)
    y1 = min(array.shape[0], py + radius + 1)
    x0 = max(0, px - radius)
    x1 = min(array.shape[1], px + radius + 1)
    values = array[y0:y1, x0:x1]
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= ~np.isclose(values, float(nodata))
    valid &= values > 0
    if not valid.any():
        return None
    return float(np.mean(values[valid]))


def validation_summary(
    samples: list[SampleResult],
    skipped: SkipCounts,
    raster_path: Path,
    observation_path: Path,
) -> dict[str, Any]:
    observed = np.array([sample.observed for sample in samples], dtype=np.float64)
    predicted = np.array([sample.predicted for sample in samples], dtype=np.float64)
    residual = predicted - observed
    summary: dict[str, Any] = {
        "raster": str(raster_path),
        "observations": str(observation_path),
        "matchup_count": int(len(samples)),
        "skipped": skipped.as_dict(),
        "linear_metrics": metric_block(observed, predicted, residual),
    }

    positive = (observed > 0) & (predicted > 0)
    if np.count_nonzero(positive) >= 2:
        observed_log = np.log10(observed[positive])
        predicted_log = np.log10(predicted[positive])
        summary["log10_metrics"] = metric_block(
            observed_log,
            predicted_log,
            predicted_log - observed_log,
        )
    return summary


def metric_block(observed: np.ndarray, predicted: np.ndarray, residual: np.ndarray) -> dict[str, float]:
    return {
        "observed_mean": finite_float(np.mean(observed)),
        "predicted_mean": finite_float(np.mean(predicted)),
        "bias": finite_float(np.mean(residual)),
        "mae": finite_float(np.mean(np.abs(residual))),
        "rmse": finite_float(np.sqrt(np.mean(residual**2))),
        "r2": finite_float(r_squared(observed, predicted)),
        "pearson_r": finite_float(pearson_r(observed, predicted)),
    }


def r_squared(observed: np.ndarray, predicted: np.ndarray) -> float:
    denominator = np.sum((observed - np.mean(observed)) ** 2)
    if denominator <= 0:
        return float("nan")
    numerator = np.sum((observed - predicted) ** 2)
    return float(1.0 - numerator / denominator)


def pearson_r(observed: np.ndarray, predicted: np.ndarray) -> float:
    if observed.size < 2:
        return float("nan")
    observed_centered = observed - np.mean(observed)
    predicted_centered = predicted - np.mean(predicted)
    denominator = math.sqrt(float(np.sum(observed_centered**2) * np.sum(predicted_centered**2)))
    if denominator <= 0:
        return float("nan")
    return float(np.sum(observed_centered * predicted_centered) / denominator)


def finite_float(value: float) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def write_matchup_csv(path: Path, samples: list[SampleResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_fields = list(samples[0].source_row.keys())
    extra_fields = [
        "raster_x",
        "raster_y",
        "observed_chlorophyll_a",
        "predicted_chlorophyll_a",
        "residual_predicted_minus_observed",
        "absolute_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*source_fields, *extra_fields])
        writer.writeheader()
        for sample in samples:
            row = dict(sample.source_row)
            row.update(
                {
                    "raster_x": sample.raster_x,
                    "raster_y": sample.raster_y,
                    "observed_chlorophyll_a": f"{sample.observed:.8g}",
                    "predicted_chlorophyll_a": f"{sample.predicted:.8g}",
                    "residual_predicted_minus_observed": f"{sample.residual:.8g}",
                    "absolute_error": f"{abs(sample.residual):.8g}",
                }
            )
            writer.writerow(row)


def write_raster_matchup_csv(path: Path, matchups: list[RasterMatchup]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "reference_pixel_x",
        "reference_pixel_y",
        "reference_x",
        "reference_y",
        "observed_reference_chlorophyll_a",
        "predicted_app_chlorophyll_a",
        "residual_predicted_minus_observed",
        "absolute_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for matchup in matchups:
            writer.writerow(
                {
                    "reference_pixel_x": matchup.pixel_x,
                    "reference_pixel_y": matchup.pixel_y,
                    "reference_x": f"{matchup.x:.8f}",
                    "reference_y": f"{matchup.y:.8f}",
                    "observed_reference_chlorophyll_a": f"{matchup.observed:.8g}",
                    "predicted_app_chlorophyll_a": f"{matchup.predicted:.8g}",
                    "residual_predicted_minus_observed": f"{matchup.residual:.8g}",
                    "absolute_error": f"{abs(matchup.residual):.8g}",
                }
            )


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def print_summary(summary: dict[str, Any], matchup_file: Path, summary_file: Path) -> None:
    metrics = summary["linear_metrics"]
    print("Chlorophyll-a validation")
    if summary.get("mode") == "reference_raster":
        print("Mode: raster-to-raster reference comparison")
        print(f"Reference raster: {summary['reference_raster']}")
        print(f"Resampled app raster: {summary['resampled_raster']}")
    print(f"Matchups: {summary['matchup_count']}")
    print(f"Bias: {format_metric(metrics['bias'])} mg/m3")
    print(f"MAE:  {format_metric(metrics['mae'])} mg/m3")
    print(f"RMSE: {format_metric(metrics['rmse'])} mg/m3")
    print(f"R2:   {format_metric(metrics['r2'])}")
    print(f"Pearson r: {format_metric(metrics['pearson_r'])}")
    print(f"Matchup CSV: {matchup_file}")
    print(f"Summary JSON: {summary_file}")


def format_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def require_columns(fieldnames: list[str], required: list[str]) -> None:
    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise ValueError(
            f"Observation CSV is missing required column(s): {', '.join(missing)}. "
            f"Available columns: {', '.join(fieldnames)}"
        )


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
