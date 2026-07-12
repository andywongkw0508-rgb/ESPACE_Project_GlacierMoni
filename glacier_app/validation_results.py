from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .boundary_validation import build_project_reference_boundary_overlay
from .config import APP_DIR, BAND_PREVIEW_CACHE, OVERLAY_BASE_SCENE_ID, RESULTS_DIR


CHL_VALIDATION_DIR = RESULTS_DIR / "chlorophyll_validation"
TURBIDITY_VALIDATION_DIR = RESULTS_DIR / "turbidity_validation"
BOUNDARY_VALIDATION_DIR = APP_DIR / "outputs" / "accuracy_check"
GLIMS_REFERENCE_FILE = (
    APP_DIR
    / "data"
    / "reference_boundaries"
    / "glims_southeast_vatnajokull"
    / "glims_glacier_outlines_project_aoi_epsg4326.geojson"
)
BOUNDARY_COMPARISON_FILE = (
    RESULTS_DIR
    / "boundary_validation"
    / "project_vs_glims_reference_overlay.png"
)
BOUNDARY_BASE_IMAGE = (
    BAND_PREVIEW_CACHE
    / "processing_results"
    / (
        f"{OVERLAY_BASE_SCENE_ID}_Visual_preprocessed_"
        "Preprocessed_Visual_p1000.png"
    )
)


@dataclass(frozen=True)
class ValidationMetric:
    label: str
    value: str


@dataclass(frozen=True)
class ValidationCardResult:
    key: str
    title: str
    status: str
    status_tone: str
    image_file: Path | None
    metrics: tuple[ValidationMetric, ...]
    note: str


def load_validation_dashboard_results() -> dict[str, ValidationCardResult]:
    return {
        "boundary_validation": _load_boundary_validation(),
        "chl_copernicus_validation": _load_chlorophyll_copernicus_validation(),
        "chl_hls_validation": _load_chlorophyll_hls_validation(),
        "turbidity_validation": _load_turbidity_validation(),
    }


def _load_boundary_validation() -> ValidationCardResult:
    image_file = _boundary_validation_image()
    final_area = _polygon_area_km2(BOUNDARY_VALIDATION_DIR / "final_polygon.geojson")
    glims_count, glims_years = _glims_summary(GLIMS_REFERENCE_FILE)
    metrics = (
        ValidationMetric("Method", "Dual overlay"),
        ValidationMetric(
            "Detected area",
            f"{final_area:,.0f} km2" if final_area is not None else "--",
        ),
        ValidationMetric(
            "GLIMS outlines",
            f"{glims_count:,}" if glims_count is not None else "--",
        ),
        ValidationMetric("GLIMS dates", glims_years or "--"),
    )
    if image_file is None:
        return _missing_result(
            "boundary_validation",
            "Glacier Boundary Validation",
            "No boundary validation overlay was found.",
            metrics,
        )
    return ValidationCardResult(
        key="boundary_validation",
        title="Glacier Boundary Validation",
        status="Historical overlay",
        status_tone="caution",
        image_file=image_file,
        metrics=metrics,
        note=(
            "Cyan is project-generated; magenta is GLIMS. The raw reference is "
            "unchanged and only harmonized spatially. No same-date IoU or F1 yet."
        ),
    )


def _load_chlorophyll_copernicus_validation() -> ValidationCardResult:
    calibrated = _latest_report(
        CHL_VALIDATION_DIR,
        lambda report: report.get("mode") == "copernicus_chl_spatial_holdout_calibration",
        pattern="*copernicus_spatial_holdout_calibration.json",
    )
    if calibrated is not None:
        _calibration_path, calibration = calibrated
        heldout = _mapping(calibration.get("heldout_metrics"))
        metrics = (
            ValidationMetric("Held-out n", _format_count(heldout.get("count"))),
            ValidationMetric("Pearson r", _format_float(heldout.get("pearson_r"), 3)),
            ValidationMetric("Bias", _format_float(heldout.get("bias"), 3)),
            ValidationMetric("RMSE", _format_float(heldout.get("rmse"), 3)),
        )
        return ValidationCardResult(
            key="chl_copernicus_validation",
            title="CHL-A vs Copernicus",
            status="Held-out calibration",
            status_tone="neutral",
            image_file=_report_image(calibration, "scatter_plot"),
            metrics=metrics,
            note=(
                "App CHL-A was calibrated on 80% of 4 km spatial cells and "
                "evaluated on the held-out 20%. Copernicus values are unchanged."
            ),
        )

    found = _latest_report(
        CHL_VALIDATION_DIR,
        lambda report: "copernicus" in str(report.get("reference_raster", "")).lower(),
    )
    if found is None:
        return _missing_result(
            "chl_copernicus_validation",
            "CHL-A vs Copernicus",
            "No Copernicus chlorophyll validation report was found.",
        )
    _report_path, report = found
    linear = _mapping(report.get("linear_metrics"))
    image_file = _report_image(report, "scatter_plot_clean", "scatter_plot")
    metrics = (
        ValidationMetric("Matchups", _format_count(report.get("matchup_count"))),
        ValidationMetric("Pearson r", _format_float(linear.get("pearson_r"), 3)),
        ValidationMetric("Bias", _format_float(linear.get("bias"), 3)),
        ValidationMetric("RMSE", _format_float(linear.get("rmse"), 3)),
    )
    return ValidationCardResult(
        key="chl_copernicus_validation",
        title="CHL-A vs Copernicus",
        status="Moderate, biased",
        status_tone="caution",
        image_file=image_file,
        metrics=metrics,
        note=(
            "Raw Copernicus values are unchanged. The app was averaged onto the "
            "4 km grid; moderate correlation remains systematically biased low."
        ),
    )


def _load_chlorophyll_hls_validation() -> ValidationCardResult:
    calibrated = _latest_report(
        CHL_VALIDATION_DIR,
        lambda report: report.get("mode") == "hls_spatial_holdout_calibration",
        pattern="*hls_spatial_holdout_calibration.json",
    )
    if calibrated is not None:
        _calibration_path, calibration = calibrated
        heldout = _mapping(calibration.get("heldout_metrics"))
        metrics = (
            ValidationMetric("Held-out n", _format_count(heldout.get("count"))),
            ValidationMetric("Pearson r", _format_float(heldout.get("pearson_r"), 3)),
            ValidationMetric("Bias", _format_float(heldout.get("bias"), 3)),
            ValidationMetric("RMSE", _format_float(heldout.get("rmse"), 3)),
        )
        return ValidationCardResult(
            key="chl_hls_validation",
            title="CHL-A vs HLS S30",
            status="Held-out calibration",
            status_tone="neutral",
            image_file=_report_image(calibration, "scatter_plot"),
            metrics=metrics,
            note=(
                "App values were calibrated on 80% of spatial blocks and evaluated "
                "on the held-out 20%. HLS reference values remain unchanged."
            ),
        )

    found = _latest_report(
        CHL_VALIDATION_DIR,
        lambda report: "hls" in str(report.get("reference_raster", "")).lower(),
    )
    if found is None:
        return _missing_result(
            "chl_hls_validation",
            "CHL-A vs HLS S30",
            "No HLS chlorophyll comparison report was found.",
        )
    _report_path, report = found
    ranges = _mapping(report.get("range_limited_metrics"))
    limited = _mapping(ranges.get("reference_chl_a_le_10_mg_m3"))
    metrics = (
        ValidationMetric("Matchups <=10", _format_count(limited.get("count"))),
        ValidationMetric("Pearson r", _format_float(limited.get("pearson_r"), 3)),
        ValidationMetric("Bias", _format_float(limited.get("bias"), 3)),
        ValidationMetric("RMSE", _format_float(limited.get("rmse"), 3)),
    )
    return ValidationCardResult(
        key="chl_hls_validation",
        title="CHL-A vs HLS S30",
        status="Same-day proxy",
        status_tone="neutral",
        image_file=_report_image(report, "scatter_plot_log"),
        metrics=metrics,
        note=(
            "Primary plot uses the predefined <=10 mg/m3 analysis domain. Raw "
            "HLS values and full-range metrics remain unchanged in the report."
        ),
    )


def _load_turbidity_validation() -> ValidationCardResult:
    calibrated = _latest_report(
        TURBIDITY_VALIDATION_DIR,
        lambda report: report.get("mode") == "turbidity_bbp_spatial_holdout_calibration",
        pattern="*turbidity_spatial_holdout_calibration.json",
    )
    if calibrated is not None:
        _calibration_path, calibration = calibrated
        heldout = _mapping(calibration.get("heldout_metrics"))
        metrics = (
            ValidationMetric("Held-out n", _format_count(heldout.get("count"))),
            ValidationMetric("Pearson r", _format_float(heldout.get("pearson_r"), 3)),
            ValidationMetric("Bias", _format_float(heldout.get("bias"), 3)),
            ValidationMetric("RMSE", _format_float(heldout.get("rmse"), 3)),
        )
        return ValidationCardResult(
            key="turbidity_validation",
            title="Turbidity vs Copernicus BBP",
            status="Provisional calibration",
            status_tone="caution",
            image_file=_report_image(calibration, "scatter_plot"),
            metrics=metrics,
            note=(
                "Percentile calibration was tested on held-out 4 km cells. The "
                "reference is unchanged; monthly BBP remains an indirect proxy."
            ),
        )

    found = _latest_report(TURBIDITY_VALIDATION_DIR, lambda _report: True)
    if found is None:
        return _missing_result(
            "turbidity_validation",
            "Turbidity vs Copernicus BBP",
            "No turbidity validation report was found.",
        )
    _report_path, report = found
    correlations = _mapping(report.get("correlation_metrics"))
    scaled = _mapping(report.get("percentile_scaled_metrics"))
    metrics = (
        ValidationMetric("Matchups", _format_count(report.get("matchup_count"))),
        ValidationMetric(
            "Pearson r",
            _format_float(correlations.get("pearson_r_bbp_vs_app_score"), 3),
        ),
        ValidationMetric(
            "Spearman r",
            _format_float(correlations.get("spearman_rank_r_bbp_vs_app_score"), 3),
        ),
        ValidationMetric("Scaled RMSE", _format_float(scaled.get("rmse"), 3)),
    )
    return ValidationCardResult(
        key="turbidity_validation",
        title="Turbidity vs Copernicus BBP",
        status="Weak proxy match",
        status_tone="weak",
        image_file=_report_image(report, "scatter_plot"),
        metrics=metrics,
        note=(
            "Raw BBP values are unchanged; both products are percentile-scaled "
            "for comparability. BBP is a monthly 4 km proxy, not direct truth."
        ),
    )


def _latest_report(
    directory: Path,
    predicate: Callable[[dict[str, Any]], bool],
    pattern: str = "*raster_validation.json",
) -> tuple[Path, dict[str, Any]] | None:
    if not directory.exists():
        return None
    candidates = sorted(
        directory.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            report = _mapping(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        if predicate(report):
            return path, report
    return None


def _report_image(report: dict[str, Any], *keys: str) -> Path | None:
    for key in keys:
        raw_path = str(report.get(key, "")).strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = APP_DIR / path
        if path.exists():
            return path
    return None


def _polygon_area_km2(path: Path) -> float | None:
    try:
        payload = _mapping(json.loads(path.read_text(encoding="utf-8")))
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            return None
        properties = _mapping(_mapping(features[0]).get("properties"))
        area_m2 = float(properties["area_m2"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return area_m2 / 1_000_000.0


def _glims_summary(path: Path) -> tuple[int | None, str | None]:
    try:
        payload = _mapping(json.loads(path.read_text(encoding="utf-8")))
        features = payload.get("features")
        if not isinstance(features, list):
            return None, None
        years = sorted(
            {
                str(_mapping(_mapping(feature).get("properties")).get("src_date", ""))[:4]
                for feature in features
                if str(_mapping(_mapping(feature).get("properties")).get("src_date", ""))[:4].isdigit()
            }
        )
    except (OSError, ValueError, TypeError):
        return None, None
    year_text = None
    if years:
        year_text = years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"
    return len(features), year_text


def _preferred_existing_file(*paths: Path) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _boundary_validation_image() -> Path | None:
    project_overlay = BOUNDARY_VALIDATION_DIR / "final_boundary_overlay.png"
    project_boundary = BOUNDARY_VALIDATION_DIR / "final_boundary.tif"
    base_image = _preferred_existing_file(BOUNDARY_BASE_IMAGE, project_overlay)
    if base_image is None:
        return None
    try:
        return build_project_reference_boundary_overlay(
            base_image,
            project_boundary,
            GLIMS_REFERENCE_FILE,
            BOUNDARY_COMPARISON_FILE,
        )
    except Exception:
        return _preferred_existing_file(
            project_overlay,
            BOUNDARY_VALIDATION_DIR / "boundary_2018_thin_overlay.png",
        )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_count(value: Any) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "--"
    if count >= 1_000_000:
        return f"{count / 1_000_000.0:.2f}M"
    if count >= 10_000:
        return f"{count / 1_000.0:.1f}K"
    return f"{count:,}"


def _format_float(value: Any, digits: int) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def _missing_result(
    key: str,
    title: str,
    note: str,
    metrics: tuple[ValidationMetric, ...] | None = None,
) -> ValidationCardResult:
    return ValidationCardResult(
        key=key,
        title=title,
        status="Not available",
        status_tone="pending",
        image_file=None,
        metrics=metrics or tuple(ValidationMetric("Status", "Missing") for _ in range(4)),
        note=note,
    )
