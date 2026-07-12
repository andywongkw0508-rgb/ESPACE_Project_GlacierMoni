from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from osgeo import gdal

try:
    from .config import BAND_PREVIEW_CACHE, PREPROCESSED_DIR, RESULTS_DIR
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import BAND_PREVIEW_CACHE, PREPROCESSED_DIR, RESULTS_DIR


PREVIEW_MAX_WIDTH = 1000
DASHBOARD_STATIC_PREVIEW_MAX_SIZE = 720
BOUNDARY_PREVIEW_VERSION = 3
BOUNDARY_MIN_LINE_RADIUS = 1
BOUNDARY_MAX_LINE_RADIUS = 1
CHL_PREVIEW_LOW_PERCENTILE = 2.0
CHL_PREVIEW_HIGH_PERCENTILE = 98.0
CHL_PREVIEW_MIN_LOG_SPAN = 0.35
CHL_OVERLAY_ALPHA = 0.58
CHL_LEGEND_MARGIN = 16
CHL_LEGEND_MIN_WIDTH = 160
CHL_LEGEND_PANEL_MIN_WIDTH = 190
CHL_LEGEND_BAR_WIDTH = 24
INDEX_METRIC_SAMPLE_SIZE = 512
INDEX_METRIC_THRESHOLDS = {
    "NDSI": 0.40,
    "NDWI": 0.20,
    "TURBIDITY": 0.65,
}


@dataclass
class ProcessingOutput:
    run_name: str
    kind: str
    label: str
    scene_id: str
    date: str
    sensor: str
    formula: str
    output_file: Path
    pixel_count: int = 0
    area_km2: float = 0.0
    source_file: Path | None = None


@dataclass(frozen=True)
class IndexMetricSummary:
    label: str
    mean: float
    median: float
    percentile_10: float
    percentile_90: float
    valid_count: int
    threshold: float | None = None
    fraction_above_threshold: float | None = None


def list_processing_outputs(run_dirs: list[Path]) -> list[ProcessingOutput]:
    outputs = []
    for run_dir in run_dirs:
        run_dir = checked_run_dir(run_dir)
        outputs.extend(read_index_outputs(run_dir))
        outputs.extend(read_mask_outputs(run_dir))
        outputs.extend(read_boundary_outputs(run_dir))
        outputs.extend(read_preprocessed_outputs(run_dir))
    outputs.sort(key=lambda item: (item.run_name, item.date, item.scene_id, item.kind, item.label))
    return outputs


def index_metric_summary(output: ProcessingOutput) -> IndexMetricSummary:
    import numpy as np

    if output.kind != "Index":
        raise ValueError(f"Index statistics require an index output, not {output.kind}.")
    gdal.UseExceptions()
    dataset = gdal.Open(str(output.output_file))
    if dataset is None:
        raise RuntimeError(f"Could not open index raster: {output.output_file}")
    scale = min(
        1.0,
        INDEX_METRIC_SAMPLE_SIZE / max(1, dataset.RasterXSize, dataset.RasterYSize),
    )
    width = max(1, int(round(dataset.RasterXSize * scale)))
    height = max(1, int(round(dataset.RasterYSize * scale)))
    band = dataset.GetRasterBand(1)
    data = band.ReadAsArray(buf_xsize=width, buf_ysize=height).astype(np.float32)
    nodata = band.GetNoDataValue()
    dataset = None

    valid = np.isfinite(data)
    if nodata is not None:
        valid &= ~np.isclose(data, np.float32(nodata))
    label = output.label.upper()
    if label == "CHL_A":
        valid &= data > 0
    values = data[valid]
    if values.size == 0:
        raise RuntimeError(f"No valid values were found in {output.label}.")

    threshold = INDEX_METRIC_THRESHOLDS.get(label)
    fraction = None
    if threshold is not None:
        fraction = float(np.mean(values >= np.float32(threshold)))
    return IndexMetricSummary(
        label=label,
        mean=float(np.mean(values)),
        median=float(np.median(values)),
        percentile_10=float(np.percentile(values, 10.0)),
        percentile_90=float(np.percentile(values, 90.0)),
        valid_count=int(values.size),
        threshold=threshold,
        fraction_above_threshold=fraction,
    )


def read_boundary_outputs(run_dir: Path) -> list[ProcessingOutput]:
    manifest = run_dir / "boundary_manifest.csv"
    if not manifest.exists():
        return []

    outputs = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            output_file = existing_output_path(row.get("output_file", ""))
            if not output_file:
                continue
            source_file = existing_output_path(row.get("source_file", ""))
            outputs.append(
                ProcessingOutput(
                    run_name=run_dir.name,
                    kind="Boundary",
                    label=f"{row.get('source_mask', '')} Boundary".strip(),
                    scene_id=row.get("scene_id", ""),
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                    formula=f"Dominant connected exterior boundary of {row.get('source_formula', '')}".strip(),
                    output_file=output_file,
                    pixel_count=parse_int(row.get("boundary_pixels", "")),
                    area_km2=parse_float(row.get("boundary_length_km", "")),
                    source_file=source_file,
                )
            )
    return outputs


def read_mask_outputs(run_dir: Path) -> list[ProcessingOutput]:
    manifest = run_dir / "mask_manifest.csv"
    if not manifest.exists():
        return []

    outputs = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            output_file = existing_output_path(row.get("output_file", ""))
            if not output_file:
                continue
            outputs.append(
                ProcessingOutput(
                    run_name=run_dir.name,
                    kind="Mask",
                    label=f"{row.get('source_index', '')} Mask".strip(),
                    scene_id=row.get("scene_id", ""),
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                    formula=row.get("formula", ""),
                    output_file=output_file,
                    pixel_count=parse_int(row.get("mask_pixels", "")),
                    area_km2=parse_float(row.get("area_km2", "")),
                )
            )
    return outputs


def read_index_outputs(run_dir: Path) -> list[ProcessingOutput]:
    manifest = run_dir / "index_manifest.csv"
    if not manifest.exists():
        return []

    outputs = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            output_file = existing_output_path(row.get("output_file", ""))
            if not output_file:
                continue
            outputs.append(
                ProcessingOutput(
                    run_name=run_dir.name,
                    kind="Index",
                    label=row.get("index", ""),
                    scene_id=row.get("scene_id", ""),
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                    formula=row.get("formula", ""),
                    output_file=output_file,
                )
            )
    return outputs


def read_preprocessed_outputs(run_dir: Path) -> list[ProcessingOutput]:
    manifest = run_dir / "preprocessed_manifest.csv"
    if not manifest.exists():
        return []

    outputs = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            output_file = existing_output_path(row.get("output_file", ""))
            if not output_file:
                continue
            source_file = existing_output_path(row.get("input_file", ""))
            outputs.append(
                ProcessingOutput(
                    run_name=run_dir.name,
                    kind="Preprocessed",
                    label=row.get("band", ""),
                    scene_id=row.get("scene_id", ""),
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                    formula="",
                    output_file=output_file,
                    source_file=source_file,
                )
            )
    return outputs


def processing_preview_png(output: ProcessingOutput) -> Path:
    source = output.output_file
    cache_dir = BAND_PREVIEW_CACHE / "processing_results"
    cache_dir.mkdir(parents=True, exist_ok=True)
    style_tag = f"p{PREVIEW_MAX_WIDTH}"
    if output.kind == "Index":
        if output.label.upper() == "CHL_A":
            style_tag += "_chl_auto_v1"
        elif output.label.upper() in {"TURBIDITY", "CHL_TURBIDITY_WARNING"}:
            style_tag += "_turbidity_v4"
    elif output.kind == "Boundary":
        style_tag += f"_continuous_v{BOUNDARY_PREVIEW_VERSION}"
    elif output.kind == "Mask":
        style_tag += "_classified_v2"
    preview_path = cache_dir / f"{source.stem}_{safe_name(output.kind)}_{safe_name(output.label)}_{style_tag}.png"
    if preview_path.exists() and preview_path.stat().st_mtime >= source.stat().st_mtime:
        return preview_path

    if output.kind == "Index":
        if output.label.upper() == "CHL_A":
            _render_chlorophyll_png(source, preview_path)
        elif output.label.upper() in {"TURBIDITY", "CHL_TURBIDITY_WARNING"}:
            _render_turbidity_png(source, preview_path)
        else:
            _render_index_png(source, preview_path)
    elif output.kind == "Boundary":
        render_boundary_preview(source, preview_path)
    elif output.kind == "Mask":
        render_mask_preview(source, preview_path)
    else:
        gdal.UseExceptions()
        opts = gdal.TranslateOptions(options=["-ot", "Byte", "-outsize", str(PREVIEW_MAX_WIDTH), "0", "-scale"])
        ds = gdal.Translate(str(preview_path), str(source), options=opts)
        if ds is None or not preview_path.exists():
            raise RuntimeError(f"Could not render {output.label} preview")
        ds = None
    return preview_path


def dashboard_static_preview_png(source: Path) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"Dashboard image is not available: {source}")
    gdal.UseExceptions()
    dataset = gdal.Open(str(source))
    if dataset is None:
        raise RuntimeError(f"Could not open dashboard image: {source}")
    width, height = dataset.RasterXSize, dataset.RasterYSize
    scale = min(1.0, DASHBOARD_STATIC_PREVIEW_MAX_SIZE / max(1, width, height))
    if scale >= 1.0:
        dataset = None
        return source

    cache_dir = BAND_PREVIEW_CACHE / "dashboard_static"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path_key = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:10]
    source_label = safe_name(source.stem)
    if len(source_label) > 96:
        label_key = hashlib.sha1(source_label.encode("utf-8")).hexdigest()[:8]
        source_label = f"{source_label[:80]}_{label_key}"
    preview_path = cache_dir / (
        f"{source_label}_{path_key}_p{DASHBOARD_STATIC_PREVIEW_MAX_SIZE}.png"
    )
    if preview_path.exists() and preview_path.stat().st_mtime >= source.stat().st_mtime:
        dataset = None
        return preview_path

    out_width = max(1, int(round(width * scale)))
    out_height = max(1, int(round(height * scale)))
    options = gdal.TranslateOptions(
        format="PNG",
        width=out_width,
        height=out_height,
        resampleAlg="bilinear",
    )
    rendered = gdal.Translate(str(preview_path), dataset, options=options)
    dataset = None
    if rendered is None:
        raise RuntimeError(f"Could not create dashboard preview: {source}")
    rendered = None
    return preview_path


def chlorophyll_overlay_png(
    chlorophyll: ProcessingOutput,
    base: ProcessingOutput,
    publish_output: bool = False,
) -> Path:
    if chlorophyll.kind != "Index" or chlorophyll.label.upper() != "CHL_A":
        raise ValueError("Select a CHL_A index result before building a chlorophyll overlay.")
    if not chlorophyll.output_file.exists():
        raise FileNotFoundError(f"Chlorophyll raster does not exist: {chlorophyll.output_file}")
    if not base.output_file.exists():
        raise FileNotFoundError(f"Base raster does not exist: {base.output_file}")

    cache_dir = BAND_PREVIEW_CACHE / "chlorophyll_overlays"
    cache_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = cache_dir / (
        f"{chlorophyll.output_file.stem}_on_{base.output_file.stem}_p{PREVIEW_MAX_WIDTH}_overlay_v4.png"
    )
    metadata_path = overlay_metadata_path(overlay_path)
    base_file = base.source_file or base.output_file
    newest_source = max(chlorophyll.output_file.stat().st_mtime, base_file.stat().st_mtime)
    if (
        overlay_path.exists()
        and metadata_path.exists()
        and overlay_path.stat().st_mtime >= newest_source
        and metadata_path.stat().st_mtime >= newest_source
    ):
        return publish_overlay_output(overlay_path, "chlorophyll_a", chlorophyll, base) if publish_output else overlay_path

    render_chlorophyll_overlay(chlorophyll.output_file, base_file, overlay_path)
    return publish_overlay_output(overlay_path, "chlorophyll_a", chlorophyll, base) if publish_output else overlay_path


def turbidity_overlay_png(
    turbidity: ProcessingOutput,
    base: ProcessingOutput,
    publish_output: bool = False,
) -> Path:
    if turbidity.kind != "Index" or turbidity.label.upper() != "TURBIDITY":
        raise ValueError("Select a TURBIDITY index result before building a turbidity overlay.")
    if not turbidity.output_file.exists():
        raise FileNotFoundError(f"Turbidity raster does not exist: {turbidity.output_file}")
    if not base.output_file.exists():
        raise FileNotFoundError(f"Base raster does not exist: {base.output_file}")

    cache_dir = BAND_PREVIEW_CACHE / "turbidity_overlays"
    cache_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = cache_dir / (
        f"{turbidity.output_file.stem}_on_{base.output_file.stem}_p{PREVIEW_MAX_WIDTH}_overlay_v1.png"
    )
    metadata_path = overlay_metadata_path(overlay_path)
    base_file = base.source_file or base.output_file
    newest_source = max(turbidity.output_file.stat().st_mtime, base_file.stat().st_mtime)
    if (
        overlay_path.exists()
        and metadata_path.exists()
        and overlay_path.stat().st_mtime >= newest_source
        and metadata_path.stat().st_mtime >= newest_source
    ):
        return publish_overlay_output(overlay_path, "turbidity", turbidity, base) if publish_output else overlay_path

    render_turbidity_overlay(turbidity.output_file, base_file, overlay_path)
    return publish_overlay_output(overlay_path, "turbidity", turbidity, base) if publish_output else overlay_path


def boundary_overlay_png(
    boundary: ProcessingOutput,
    base: ProcessingOutput,
    publish_output: bool = False,
) -> Path:
    if boundary.kind != "Boundary":
        raise ValueError("Select a boundary result before building a boundary overlay.")
    if not boundary.output_file.exists():
        raise FileNotFoundError(f"Boundary raster does not exist: {boundary.output_file}")
    if not base.output_file.exists():
        raise FileNotFoundError(f"Base raster does not exist: {base.output_file}")

    cache_dir = BAND_PREVIEW_CACHE / "boundary_overlays"
    cache_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = cache_dir / (
        f"{boundary.output_file.stem}_on_{base.output_file.stem}_p{PREVIEW_MAX_WIDTH}"
        f"_overlay_v{BOUNDARY_PREVIEW_VERSION}.png"
    )
    metadata_path = overlay_metadata_path(overlay_path)
    base_file = base.source_file or base.output_file
    newest_source = max(boundary.output_file.stat().st_mtime, base_file.stat().st_mtime)
    if (
        overlay_path.exists()
        and metadata_path.exists()
        and overlay_path.stat().st_mtime >= newest_source
        and metadata_path.stat().st_mtime >= newest_source
    ):
        return publish_overlay_output(overlay_path, "boundary", boundary, base) if publish_output else overlay_path

    render_boundary_overlay(boundary.output_file, base_file, overlay_path)
    return publish_overlay_output(overlay_path, "boundary", boundary, base) if publish_output else overlay_path


def overlay_coordinate_region(overlay_path: Path) -> tuple[int, int, int, int] | None:
    metadata_path = overlay_metadata_path(overlay_path)
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    region = metadata.get("coordinate_region")
    if not isinstance(region, list) or len(region) != 4:
        return None
    try:
        x, y, width, height = [int(value) for value in region]
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def publish_overlay_output(
    preview_path: Path,
    overlay_kind: str,
    source: ProcessingOutput,
    base: ProcessingOutput,
) -> Path:
    output_path = overlay_output_path(overlay_kind, source, base)
    shutil.copy2(preview_path, output_path)
    metadata_path = overlay_metadata_path(preview_path)
    if metadata_path.exists():
        shutil.copy2(metadata_path, overlay_metadata_path(output_path))
    return output_path


def overlay_output_path(overlay_kind: str, source: ProcessingOutput, base: ProcessingOutput) -> Path:
    year = source.date[:4] if len(source.date) >= 4 and source.date[:4].isdigit() else "unknown_year"
    target_dir = RESULTS_DIR / "overlays" / safe_name(overlay_kind.upper()) / year / safe_name(source.scene_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_file = base.source_file or base.output_file
    return target_dir / (
        f"{safe_name(source.output_file.stem)}_on_{safe_name(base_file.stem)}_overlay.png"
    )


def _render_index_png(source: Path, preview_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    ds = gdal.Open(str(source))
    if ds is None:
        raise RuntimeError(f"Cannot open {source}")

    full_w, full_h = ds.RasterXSize, ds.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / full_w)
    out_w = max(1, int(round(full_w * scale)))
    out_h = max(1, int(round(full_h * scale)))

    band = ds.GetRasterBand(1)
    data = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h).astype(np.float32)
    nodata_val = band.GetNoDataValue()
    ds = None

    valid = np.ones(data.shape, dtype=bool)
    if nodata_val is not None:
        valid &= ~np.isclose(data, np.float32(nodata_val))

    grey = np.clip((data + 1.0) / 2.0 * 255.0, 0, 255).astype(np.uint8)
    alpha = np.where(valid, np.uint8(255), np.uint8(0))

    mem_drv = gdal.GetDriverByName("MEM")
    mem_ds = mem_drv.Create("", out_w, out_h, 4, gdal.GDT_Byte)
    for i, arr in enumerate([grey, grey, grey, alpha], start=1):
        mem_ds.GetRasterBand(i).WriteArray(arr)
    from osgeo.gdalconst import GCI_RedBand, GCI_GreenBand, GCI_BlueBand, GCI_AlphaBand
    mem_ds.GetRasterBand(1).SetColorInterpretation(GCI_RedBand)
    mem_ds.GetRasterBand(2).SetColorInterpretation(GCI_GreenBand)
    mem_ds.GetRasterBand(3).SetColorInterpretation(GCI_BlueBand)
    mem_ds.GetRasterBand(4).SetColorInterpretation(GCI_AlphaBand)

    png_drv = gdal.GetDriverByName("PNG")
    out_ds = png_drv.CreateCopy(str(preview_path), mem_ds)
    out_ds = None
    mem_ds = None


def _render_chlorophyll_png(source: Path, preview_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    ds = gdal.Open(str(source))
    if ds is None:
        raise RuntimeError(f"Cannot open {source}")

    full_w, full_h = ds.RasterXSize, ds.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / full_w)
    out_w = max(1, int(round(full_w * scale)))
    out_h = max(1, int(round(full_h * scale)))

    band = ds.GetRasterBand(1)
    data = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h).astype(np.float32)
    nodata_val = band.GetNoDataValue()
    ds = None

    valid = np.isfinite(data) & (data > 0)
    if nodata_val is not None:
        valid &= ~np.isclose(data, np.float32(nodata_val))

    scaled, _low_value, _high_value = adaptive_chlorophyll_scale(data, valid)
    red, green, blue = chlorophyll_ramp(scaled)
    alpha = np.where(valid, np.uint8(255), np.uint8(0))

    mem_drv = gdal.GetDriverByName("MEM")
    mem_ds = mem_drv.Create("", out_w, out_h, 4, gdal.GDT_Byte)
    for i, arr in enumerate([red, green, blue, alpha], start=1):
        mem_ds.GetRasterBand(i).WriteArray(arr)
    from osgeo.gdalconst import GCI_RedBand, GCI_GreenBand, GCI_BlueBand, GCI_AlphaBand
    mem_ds.GetRasterBand(1).SetColorInterpretation(GCI_RedBand)
    mem_ds.GetRasterBand(2).SetColorInterpretation(GCI_GreenBand)
    mem_ds.GetRasterBand(3).SetColorInterpretation(GCI_BlueBand)
    mem_ds.GetRasterBand(4).SetColorInterpretation(GCI_AlphaBand)

    png_drv = gdal.GetDriverByName("PNG")
    out_ds = png_drv.CreateCopy(str(preview_path), mem_ds)
    out_ds = None
    mem_ds = None


def _render_turbidity_png(source: Path, preview_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    ds = gdal.Open(str(source))
    if ds is None:
        raise RuntimeError(f"Cannot open {source}")

    full_w, full_h = ds.RasterXSize, ds.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / full_w)
    out_w = max(1, int(round(full_w * scale)))
    out_h = max(1, int(round(full_h * scale)))

    band = ds.GetRasterBand(1)
    data = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h).astype(np.float32)
    nodata_val = band.GetNoDataValue()
    ds = None

    valid = np.isfinite(data)
    if nodata_val is not None:
        valid &= ~np.isclose(data, np.float32(nodata_val))

    red, green, blue = turbidity_ramp(np.clip(data, 0.0, 1.0))
    alpha = np.where(valid, np.uint8(255), np.uint8(0))
    rgb = np.stack([red, green, blue], axis=0)
    canvas_rgb, canvas_alpha = compose_turbidity_preview_canvas(rgb, alpha)
    write_rgba_png(preview_path, canvas_rgb, canvas_alpha)
    write_overlay_metadata(preview_path, out_w, out_h)


def render_chlorophyll_overlay(chlorophyll_source: Path, base_source: Path, overlay_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    chl_ds = gdal.Open(str(chlorophyll_source))
    if chl_ds is None:
        raise RuntimeError(f"Cannot open {chlorophyll_source}")

    full_w, full_h = chl_ds.RasterXSize, chl_ds.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / full_w)
    out_w = max(1, int(round(full_w * scale)))
    out_h = max(1, int(round(full_h * scale)))
    bounds = dataset_bounds(chl_ds)
    projection = chl_ds.GetProjection()

    band = chl_ds.GetRasterBand(1)
    chl_data = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h).astype(np.float32)
    nodata_val = band.GetNoDataValue()
    chl_ds = None

    chl_valid = np.isfinite(chl_data) & (chl_data > 0)
    if nodata_val is not None:
        chl_valid &= ~np.isclose(chl_data, np.float32(nodata_val))

    scaled, low_value, high_value = adaptive_chlorophyll_scale(chl_data, chl_valid)
    chl_red, chl_green, chl_blue = chlorophyll_ramp(scaled)
    base_rgb, base_valid = base_rgb_for_grid(base_source, projection, bounds, out_w, out_h)

    alpha = np.float32(CHL_OVERLAY_ALPHA)
    rgb = base_rgb.astype(np.float32)
    for band_index, chl_band in enumerate([chl_red, chl_green, chl_blue]):
        rgb[band_index][chl_valid] = (
            rgb[band_index][chl_valid] * (np.float32(1.0) - alpha)
            + chl_band[chl_valid].astype(np.float32) * alpha
        )
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    out_alpha = np.where(base_valid | chl_valid, np.uint8(255), np.uint8(0))
    canvas_rgb, canvas_alpha = compose_chlorophyll_overlay_canvas(rgb, out_alpha, low_value, high_value)
    write_rgba_png(overlay_path, canvas_rgb, canvas_alpha)
    write_overlay_metadata(overlay_path, out_w, out_h)


def render_turbidity_overlay(turbidity_source: Path, base_source: Path, overlay_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    turbidity_ds = gdal.Open(str(turbidity_source))
    if turbidity_ds is None:
        raise RuntimeError(f"Cannot open {turbidity_source}")

    full_w, full_h = turbidity_ds.RasterXSize, turbidity_ds.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / full_w)
    out_w = max(1, int(round(full_w * scale)))
    out_h = max(1, int(round(full_h * scale)))
    bounds = dataset_bounds(turbidity_ds)
    projection = turbidity_ds.GetProjection()

    band = turbidity_ds.GetRasterBand(1)
    data = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h).astype(np.float32)
    nodata_val = band.GetNoDataValue()
    turbidity_ds = None

    valid = np.isfinite(data)
    if nodata_val is not None:
        valid &= ~np.isclose(data, np.float32(nodata_val))

    overlay_red, overlay_green, overlay_blue = turbidity_ramp(np.clip(data, 0.0, 1.0))
    base_rgb, base_valid = base_rgb_for_grid(base_source, projection, bounds, out_w, out_h)

    alpha = np.float32(CHL_OVERLAY_ALPHA)
    rgb = base_rgb.astype(np.float32)
    for band_index, overlay_band in enumerate([overlay_red, overlay_green, overlay_blue]):
        rgb[band_index][valid] = (
            rgb[band_index][valid] * (np.float32(1.0) - alpha)
            + overlay_band[valid].astype(np.float32) * alpha
        )
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    out_alpha = np.where(base_valid | valid, np.uint8(255), np.uint8(0))
    canvas_rgb, canvas_alpha = compose_turbidity_preview_canvas(rgb, out_alpha)
    write_rgba_png(overlay_path, canvas_rgb, canvas_alpha)
    write_overlay_metadata(overlay_path, out_w, out_h)


def render_boundary_preview(boundary_source: Path, preview_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    boundary_ds = gdal.Open(str(boundary_source))
    if boundary_ds is None:
        raise RuntimeError(f"Cannot open {boundary_source}")

    out_w, out_h = boundary_preview_dimensions(boundary_ds)
    mask = boundary_display_mask(boundary_source, boundary_ds, out_w, out_h)
    boundary_ds = None
    mask = thicken_mask(mask, radius=boundary_line_radius(out_w, out_h))

    rgb = np.zeros((3, out_h, out_w), dtype=np.uint8)
    rgb[:, mask] = np.uint8(255)
    alpha = np.full((out_h, out_w), np.uint8(255), dtype=np.uint8)
    write_rgba_png(preview_path, rgb, alpha)


def render_mask_preview(mask_source: Path, preview_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    dataset = gdal.Open(str(mask_source))
    if dataset is None:
        raise RuntimeError(f"Cannot open {mask_source}")
    out_w, out_h = boundary_preview_dimensions(dataset)
    band = dataset.GetRasterBand(1)
    values = band.ReadAsArray(buf_xsize=out_w, buf_ysize=out_h)
    nodata = band.GetNoDataValue()
    dataset = None

    unknown = np.zeros(values.shape, dtype=bool)
    if nodata is not None:
        unknown = values == nodata
    glacier = (values > 0) & ~unknown

    rgb = np.zeros((3, out_h, out_w), dtype=np.uint8)
    rgb[:, unknown] = np.uint8(72)
    rgb[:, glacier] = np.uint8(255)
    alpha = np.full((out_h, out_w), np.uint8(255), dtype=np.uint8)
    write_rgba_png(preview_path, rgb, alpha)


def render_boundary_overlay(boundary_source: Path, base_source: Path, overlay_path: Path) -> None:
    import numpy as np

    gdal.UseExceptions()
    boundary_ds = gdal.Open(str(boundary_source))
    if boundary_ds is None:
        raise RuntimeError(f"Cannot open {boundary_source}")

    out_w, out_h = boundary_preview_dimensions(boundary_ds)
    bounds = dataset_bounds(boundary_ds)
    projection = boundary_ds.GetProjection()
    mask = boundary_display_mask(boundary_source, boundary_ds, out_w, out_h)
    boundary_ds = None
    line_radius = boundary_line_radius(out_w, out_h)
    mask = thicken_mask(mask, radius=line_radius)

    rgb, base_valid = base_rgb_for_grid(base_source, projection, bounds, out_w, out_h)
    if mask.any():
        halo = thicken_mask(mask, radius=1)
        rgb[0][halo] = 20
        rgb[1][halo] = 29
        rgb[2][halo] = 33
        rgb[0][mask] = 245
        rgb[1][mask] = 218
        rgb[2][mask] = 63
    alpha = np.where(base_valid | mask, np.uint8(255), np.uint8(0))
    write_rgba_png(overlay_path, rgb, alpha)
    write_overlay_metadata(overlay_path, out_w, out_h)


def boundary_preview_dimensions(dataset: gdal.Dataset) -> tuple[int, int]:
    full_w, full_h = dataset.RasterXSize, dataset.RasterYSize
    scale = min(1.0, PREVIEW_MAX_WIDTH / max(1, full_w, full_h))
    return max(1, int(round(full_w * scale))), max(1, int(round(full_h * scale)))


def boundary_line_radius(width: int, height: int) -> int:
    scaled = int(round(max(width, height) / 500.0))
    return max(BOUNDARY_MIN_LINE_RADIUS, min(BOUNDARY_MAX_LINE_RADIUS, scaled))


def boundary_display_mask(
    boundary_source: Path,
    boundary_ds: gdal.Dataset,
    width: int,
    height: int,
):
    """Preserve thin linework while reducing a full-resolution boundary raster."""
    import numpy as np

    bounds = dataset_bounds(boundary_ds)
    max_resampling = getattr(gdal, "GRA_Max", gdal.GRA_NearestNeighbour)
    reduced = gdal.Warp(
        "",
        boundary_ds,
        format="MEM",
        width=width,
        height=height,
        outputBounds=bounds,
        dstSRS=boundary_ds.GetProjection(),
        srcNodata=0,
        dstNodata=0,
        resampleAlg=max_resampling,
    )
    if reduced is None:
        raise RuntimeError(f"Could not reduce boundary raster: {boundary_source}")

    vector_path = boundary_source.with_suffix(".geojson")
    if vector_path.exists():
        vector = gdal.OpenEx(str(vector_path), gdal.OF_VECTOR)
        if vector is not None:
            layer = vector.GetLayer(0)
            error = gdal.RasterizeLayer(
                reduced,
                [1],
                layer,
                burn_values=[1],
                options=["ALL_TOUCHED=TRUE"],
            )
            vector = None
            if error != 0:
                raise RuntimeError(f"Could not rasterize boundary vector: {vector_path}")

    mask = reduced.GetRasterBand(1).ReadAsArray() > 0
    reduced = None
    return np.asarray(mask, dtype=bool)


def base_rgb_for_grid(
    base_source: Path,
    projection: str,
    bounds: tuple[float, float, float, float],
    width: int,
    height: int,
):
    import numpy as np

    base_ds = gdal.Open(str(base_source))
    if base_ds is None:
        raise RuntimeError(f"Cannot open base raster: {base_source}")
    warped = gdal.Warp(
        "",
        base_ds,
        format="MEM",
        width=width,
        height=height,
        outputBounds=bounds,
        dstSRS=projection,
        resampleAlg=gdal.GRA_Bilinear,
    )
    base_ds = None
    if warped is None:
        raise RuntimeError(f"Could not align base raster: {base_source}")

    if warped.RasterCount >= 3:
        arrays = []
        valid = np.ones((height, width), dtype=bool)
        for band_index in (1, 2, 3):
            band = warped.GetRasterBand(band_index)
            array = band.ReadAsArray().astype(np.float32)
            band_valid = valid_band_mask(array, band.GetNoDataValue())
            arrays.append(scale_display_band(array, band_valid))
            valid &= band_valid
        warped = None
        return np.stack(arrays, axis=0), valid

    band = warped.GetRasterBand(1)
    array = band.ReadAsArray().astype(np.float32)
    valid = valid_band_mask(array, band.GetNoDataValue())
    grey = scale_display_band(array, valid)
    warped = None
    return np.stack([grey, grey, grey], axis=0), valid


def thicken_mask(mask, radius: int):
    import numpy as np

    if radius <= 0:
        return mask
    result = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(mask)
            src_y0 = max(0, -dy)
            src_y1 = mask.shape[0] - max(0, dy)
            src_x0 = max(0, -dx)
            src_x1 = mask.shape[1] - max(0, dx)
            dst_y0 = max(0, dy)
            dst_y1 = mask.shape[0] - max(0, -dy)
            dst_x0 = max(0, dx)
            dst_x1 = mask.shape[1] - max(0, -dx)
            shifted[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
            result |= shifted
    return result


def valid_band_mask(array, nodata):
    import numpy as np

    valid = np.isfinite(array)
    if nodata is not None:
        valid &= ~np.isclose(array, np.float32(nodata))
    return valid


def scale_display_band(array, valid):
    import numpy as np

    result = np.zeros(array.shape, dtype=np.uint8)
    values = array[valid]
    if values.size == 0:
        return result
    low = float(np.percentile(values, 2.0))
    high = float(np.percentile(values, 98.0))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(values))
        high = float(np.max(values))
    if high <= low:
        high = low + 1.0
    scaled = (array - np.float32(low)) * np.float32(255.0 / (high - low))
    result[valid] = np.clip(scaled[valid], 0, 255).astype(np.uint8)
    return result


def dataset_bounds(dataset: gdal.Dataset) -> tuple[float, float, float, float]:
    gt = dataset.GetGeoTransform()
    width = dataset.RasterXSize
    height = dataset.RasterYSize
    points = [
        transform_pixel(gt, 0, 0),
        transform_pixel(gt, width, 0),
        transform_pixel(gt, width, height),
        transform_pixel(gt, 0, height),
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def transform_pixel(
    geo_transform: tuple[float, float, float, float, float, float],
    pixel_x: int,
    pixel_y: int,
) -> tuple[float, float]:
    x = geo_transform[0] + pixel_x * geo_transform[1] + pixel_y * geo_transform[2]
    y = geo_transform[3] + pixel_x * geo_transform[4] + pixel_y * geo_transform[5]
    return x, y


def write_rgba_png(path: Path, rgb, alpha) -> None:
    mem_drv = gdal.GetDriverByName("MEM")
    mem_ds = mem_drv.Create(str(""), rgb.shape[2], rgb.shape[1], 4, gdal.GDT_Byte)
    if mem_ds is None:
        raise RuntimeError("Could not create in-memory overlay image.")
    for band_index, array in enumerate([rgb[0], rgb[1], rgb[2], alpha], start=1):
        mem_ds.GetRasterBand(band_index).WriteArray(array)
    from osgeo.gdalconst import GCI_RedBand, GCI_GreenBand, GCI_BlueBand, GCI_AlphaBand
    mem_ds.GetRasterBand(1).SetColorInterpretation(GCI_RedBand)
    mem_ds.GetRasterBand(2).SetColorInterpretation(GCI_GreenBand)
    mem_ds.GetRasterBand(3).SetColorInterpretation(GCI_BlueBand)
    mem_ds.GetRasterBand(4).SetColorInterpretation(GCI_AlphaBand)
    png_drv = gdal.GetDriverByName("PNG")
    out_ds = png_drv.CreateCopy(str(path), mem_ds)
    if out_ds is None:
        raise RuntimeError(f"Could not create overlay PNG: {path}")
    out_ds = None
    mem_ds = None


def chlorophyll_ramp(values):
    import numpy as np

    stops = np.array(
        [
            [45, 0, 145],
            [0, 50, 210],
            [0, 180, 230],
            [0, 175, 70],
            [235, 220, 45],
            [245, 115, 20],
            [190, 0, 0],
        ],
        dtype=np.float32,
    )
    values = np.clip(values, 0.0, 1.0)
    positions = values * (len(stops) - 1)
    lower = np.floor(positions).astype(np.int16)
    upper = np.clip(lower + 1, 0, len(stops) - 1)
    frac = (positions - lower)[..., None]
    rgb = stops[lower] * (1.0 - frac) + stops[upper] * frac
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return rgb[..., 0], rgb[..., 1], rgb[..., 2]


def turbidity_ramp(values):
    import numpy as np

    stops = np.array(
        [
            [21, 44, 114],
            [0, 128, 190],
            [42, 184, 154],
            [241, 218, 63],
            [238, 114, 36],
            [170, 28, 28],
        ],
        dtype=np.float32,
    )
    values = np.clip(values, 0.0, 1.0)
    positions = values * (len(stops) - 1)
    lower = np.floor(positions).astype(np.int16)
    upper = np.clip(lower + 1, 0, len(stops) - 1)
    frac = (positions - lower)[..., None]
    rgb = stops[lower] * (1.0 - frac) + stops[upper] * frac
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return rgb[..., 0], rgb[..., 1], rgb[..., 2]


def adaptive_chlorophyll_scale(data, valid):
    import numpy as np

    scaled = np.zeros(data.shape, dtype=np.float32)
    valid_values = data[valid]
    if valid_values.size == 0:
        return scaled, 0.0, 0.0

    log_values = np.log10(np.maximum(valid_values.astype(np.float32), np.float32(1e-6)))
    low = float(np.percentile(log_values, CHL_PREVIEW_LOW_PERCENTILE))
    high = float(np.percentile(log_values, CHL_PREVIEW_HIGH_PERCENTILE))
    if not np.isfinite(low) or not np.isfinite(high):
        return scaled, 0.0, 0.0

    if high - low < CHL_PREVIEW_MIN_LOG_SPAN:
        center = (low + high) / 2.0
        low = center - CHL_PREVIEW_MIN_LOG_SPAN / 2.0
        high = center + CHL_PREVIEW_MIN_LOG_SPAN / 2.0

    log_data = np.log10(np.maximum(data.astype(np.float32), np.float32(1e-6)))
    scaled_values = (log_data - np.float32(low)) / np.float32(high - low)
    scaled[valid] = np.clip(scaled_values[valid], 0.0, 1.0)
    return scaled, 10**low, 10**high


def compose_chlorophyll_overlay_canvas(rgb, alpha, low_value: float, high_value: float):
    import numpy as np

    map_height, map_width = alpha.shape
    panel_width = chlorophyll_legend_panel_width(low_value, high_value)
    canvas_width = map_width + panel_width

    canvas_rgb = np.empty((3, map_height, canvas_width), dtype=np.uint8)
    canvas_rgb[:] = np.array([235, 244, 247], dtype=np.uint8)[:, None, None]
    canvas_rgb[:, :, :map_width] = rgb
    divider_x = map_width
    canvas_rgb[:, :, divider_x : divider_x + 1] = np.array([184, 202, 210], dtype=np.uint8)[:, None, None]

    canvas_alpha = np.full((map_height, canvas_width), 255, dtype=np.uint8)
    canvas_alpha[:, :map_width] = alpha

    legend_region = (map_width, 0, canvas_width, map_height)
    draw_chlorophyll_legend(canvas_rgb, low_value, high_value, legend_region)
    return canvas_rgb, canvas_alpha


def compose_turbidity_preview_canvas(rgb, alpha):
    import numpy as np

    map_height, map_width = alpha.shape
    panel_width = CHL_LEGEND_PANEL_MIN_WIDTH
    canvas_width = map_width + panel_width

    canvas_rgb = np.empty((3, map_height, canvas_width), dtype=np.uint8)
    canvas_rgb[:] = np.array([235, 244, 247], dtype=np.uint8)[:, None, None]
    canvas_rgb[:, :, :map_width] = rgb
    canvas_rgb[:, :, map_width : map_width + 1] = np.array([184, 202, 210], dtype=np.uint8)[:, None, None]

    canvas_alpha = np.full((map_height, canvas_width), 255, dtype=np.uint8)
    canvas_alpha[:, :map_width] = alpha

    legend_region = (map_width, 0, canvas_width, map_height)
    draw_turbidity_legend(canvas_rgb, legend_region)
    return canvas_rgb, canvas_alpha


def chlorophyll_legend_panel_width(low_value: float, high_value: float) -> int:
    mid_value = (low_value * high_value) ** 0.5 if low_value > 0 and high_value > 0 else 0.0
    label_width = max(
        small_text_width(format_chlorophyll_tick(value), 2)
        for value in (low_value, mid_value, high_value)
    )
    title_width = small_text_width("CHL-A", 2)
    required = (
        CHL_LEGEND_MARGIN * 2
        + 18
        + CHL_LEGEND_BAR_WIDTH
        + 14
        + max(label_width, title_width)
        + 18
    )
    return max(CHL_LEGEND_PANEL_MIN_WIDTH, required)


def draw_chlorophyll_legend(
    rgb,
    low_value: float,
    high_value: float,
    legend_region: tuple[int, int, int, int] | None = None,
) -> None:
    import numpy as np

    height, width = rgb.shape[1], rgb.shape[2]
    x0, y0, x1, y1 = legend_bounds(width, height, legend_region)
    if x1 <= x0 or y1 <= y0:
        return

    rgb[:, y0:y1, x0:x1] = np.array([244, 248, 249], dtype=np.uint8)[:, None, None]
    rgb[:, y0, x0:x1] = 70
    rgb[:, y1 - 1, x0:x1] = 70
    rgb[:, y0:y1, x0] = 70
    rgb[:, y0:y1, x1 - 1] = 70

    title_x = x0 + 12
    title_y = y0 + 12
    draw_small_text(rgb, "CHL-A", title_x, title_y, (20, 29, 33), 2)
    draw_small_text(rgb, "OVERLAY", title_x, title_y + 20, (20, 29, 33), 1)
    draw_small_text(rgb, "MG/M3", title_x, title_y + 34, (20, 29, 33), 1)

    bar_x0 = x0 + 18
    bar_x1 = min(bar_x0 + CHL_LEGEND_BAR_WIDTH, x1 - 86)
    if bar_x1 <= bar_x0:
        return
    bar_y0 = y0 + 70
    bar_y1 = y1 - 24
    bar_height = max(1, bar_y1 - bar_y0)
    gradient = np.linspace(1.0, 0.0, bar_height, dtype=np.float32)[:, None]
    red, green, blue = chlorophyll_ramp(np.repeat(gradient, max(1, bar_x1 - bar_x0), axis=1))
    rgb[:, bar_y0:bar_y1, bar_x0:bar_x1] = np.stack([red, green, blue], axis=0)
    rgb[:, bar_y0, bar_x0:bar_x1] = 30
    rgb[:, bar_y1 - 1, bar_x0:bar_x1] = 30
    rgb[:, bar_y0:bar_y1, bar_x0] = 30
    rgb[:, bar_y0:bar_y1, bar_x1 - 1] = 30

    mid_value = (low_value * high_value) ** 0.5 if low_value > 0 and high_value > 0 else 0.0
    low_text = format_chlorophyll_tick(low_value)
    mid_text = format_chlorophyll_tick(mid_value)
    high_text = format_chlorophyll_tick(high_value)
    label_x = bar_x1 + 14
    high_y = max(bar_y0 - 4, y0 + 60)
    mid_y = (bar_y0 + bar_y1) // 2 - 6
    low_y = min(bar_y1 - 10, y1 - 32)
    draw_tick(rgb, bar_x1, bar_y0, (20, 29, 33))
    draw_tick(rgb, bar_x1, (bar_y0 + bar_y1) // 2, (20, 29, 33))
    draw_tick(rgb, bar_x1, bar_y1 - 1, (20, 29, 33))
    draw_small_text(rgb, high_text, label_x, high_y, (20, 29, 33), 2)
    draw_small_text(rgb, mid_text, label_x, mid_y, (20, 29, 33), 2)
    draw_small_text(rgb, low_text, label_x, low_y, (20, 29, 33), 2)


def draw_turbidity_legend(
    rgb,
    legend_region: tuple[int, int, int, int],
) -> None:
    import numpy as np

    height, width = rgb.shape[1], rgb.shape[2]
    x0, y0, x1, y1 = legend_bounds(width, height, legend_region)
    if x1 <= x0 or y1 <= y0:
        return

    rgb[:, y0:y1, x0:x1] = np.array([244, 248, 249], dtype=np.uint8)[:, None, None]
    rgb[:, y0, x0:x1] = 70
    rgb[:, y1 - 1, x0:x1] = 70
    rgb[:, y0:y1, x0] = 70
    rgb[:, y0:y1, x1 - 1] = 70

    title_x = x0 + 12
    title_y = y0 + 12
    draw_small_text(rgb, "TURBIDITY", title_x, title_y, (20, 29, 33), 1)
    draw_small_text(rgb, "SCORE 0-1", title_x, title_y + 14, (20, 29, 33), 1)

    bar_x0 = x0 + 18
    bar_x1 = min(bar_x0 + CHL_LEGEND_BAR_WIDTH, x1 - 86)
    if bar_x1 <= bar_x0:
        return
    bar_y0 = y0 + 58
    bar_y1 = y1 - 24
    bar_height = max(1, bar_y1 - bar_y0)
    gradient = np.linspace(1.0, 0.0, bar_height, dtype=np.float32)[:, None]
    red, green, blue = turbidity_ramp(np.repeat(gradient, max(1, bar_x1 - bar_x0), axis=1))
    rgb[:, bar_y0:bar_y1, bar_x0:bar_x1] = np.stack([red, green, blue], axis=0)
    rgb[:, bar_y0, bar_x0:bar_x1] = 30
    rgb[:, bar_y1 - 1, bar_x0:bar_x1] = 30
    rgb[:, bar_y0:bar_y1, bar_x0] = 30
    rgb[:, bar_y0:bar_y1, bar_x1 - 1] = 30

    label_x = bar_x1 + 14
    high_y = max(bar_y0 - 4, y0 + 52)
    mid_y = (bar_y0 + bar_y1) // 2 - 6
    low_y = min(bar_y1 - 10, y1 - 32)
    draw_tick(rgb, bar_x1, bar_y0, (20, 29, 33))
    draw_tick(rgb, bar_x1, (bar_y0 + bar_y1) // 2, (20, 29, 33))
    draw_tick(rgb, bar_x1, bar_y1 - 1, (20, 29, 33))
    draw_small_text(rgb, "1.0", label_x, high_y, (20, 29, 33), 2)
    draw_small_text(rgb, "0.5", label_x, mid_y, (20, 29, 33), 2)
    draw_small_text(rgb, "0.0", label_x, low_y, (20, 29, 33), 2)


def make_legend_area_opaque(alpha) -> None:
    height, width = alpha.shape
    x0, y0, x1, y1 = legend_bounds(width, height)
    if x1 > x0 and y1 > y0:
        alpha[y0:y1, x0:x1] = 255


def legend_bounds(
    width: int,
    height: int,
    region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    if region is None:
        region = (0, 0, width, height)
    rx0, ry0, rx1, ry1 = region
    rx0 = max(0, min(width, rx0))
    ry0 = max(0, min(height, ry0))
    rx1 = max(rx0, min(width, rx1))
    ry1 = max(ry0, min(height, ry1))
    region_width = rx1 - rx0
    region_height = ry1 - ry0
    available_width = region_width - CHL_LEGEND_MARGIN * 2
    available_height = region_height - CHL_LEGEND_MARGIN * 2
    if available_width <= 0 or available_height <= 0:
        return 0, 0, 0, 0
    legend_width = min(max(CHL_LEGEND_MIN_WIDTH, available_width), available_width)
    legend_height = min(max(280, int(region_height * 0.72)), available_height)
    x0 = rx0 + (region_width - legend_width) // 2
    y0 = ry0 + (region_height - legend_height) // 2
    return x0, y0, x0 + legend_width, y0 + legend_height


def overlay_metadata_path(overlay_path: Path) -> Path:
    return overlay_path.with_suffix(overlay_path.suffix + ".json")


def write_overlay_metadata(overlay_path: Path, map_width: int, map_height: int) -> None:
    metadata = {"coordinate_region": [0, 0, int(map_width), int(map_height)]}
    with overlay_metadata_path(overlay_path).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle)


def draw_tick(rgb, x: int, y: int, color: tuple[int, int, int]) -> None:
    import numpy as np

    color_array = np.array(color, dtype=np.uint8)[:, None]
    x1 = min(rgb.shape[2], x + 9)
    if 0 <= y < rgb.shape[1] and x < x1:
        rgb[:, y, x:x1] = color_array


def format_chlorophyll_tick(value: float) -> str:
    if value <= 0:
        return "0"
    if value < 0.1:
        return f"{value:.3f}"
    if value < 1:
        return f"{value:.2f}"
    if value < 10:
        return f"{value:.1f}"
    return f"{value:.0f}"


TEXT_FONT = {
    " ": ("000", "000", "000", "000", "000", "000", "000"),
    "-": ("000", "000", "000", "111", "000", "000", "000"),
    ".": ("0", "0", "0", "0", "0", "0", "1"),
    "/": ("0001", "0001", "0010", "0010", "0100", "0100", "1000"),
    "0": ("111", "101", "101", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "010", "010", "111"),
    "2": ("111", "001", "001", "111", "100", "100", "111"),
    "3": ("111", "001", "001", "111", "001", "001", "111"),
    "4": ("101", "101", "101", "111", "001", "001", "001"),
    "5": ("111", "100", "100", "111", "001", "001", "111"),
    "6": ("111", "100", "100", "111", "101", "101", "111"),
    "7": ("111", "001", "001", "010", "010", "100", "100"),
    "8": ("111", "101", "101", "111", "101", "101", "111"),
    "9": ("111", "101", "101", "111", "001", "001", "111"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("111", "010", "010", "010", "010", "010", "111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
}


def draw_small_text(rgb, text: str, x: int, y: int, color: tuple[int, int, int], scale: int) -> None:
    import numpy as np

    cursor = x
    color_array = np.array(color, dtype=np.uint8)[:, None, None]
    for char in text.upper():
        glyph = TEXT_FONT.get(char, TEXT_FONT[" "])
        for row_index, row in enumerate(glyph):
            for col_index, value in enumerate(row):
                if value != "1":
                    continue
                y0 = y + row_index * scale
                x0 = cursor + col_index * scale
                if 0 <= y0 < rgb.shape[1] and 0 <= x0 < rgb.shape[2]:
                    rgb[:, y0 : y0 + scale, x0 : x0 + scale] = color_array
        cursor += (len(glyph[0]) + 1) * scale


def small_text_width(text: str, scale: int) -> int:
    width = 0
    for char in text.upper():
        glyph = TEXT_FONT.get(char, TEXT_FONT[" "])
        width += (len(glyph[0]) + 1) * scale
    return max(0, width - scale)


def draw_centered_small_text(rgb, text: str, center_x: int, y: int, color: tuple[int, int, int], scale: int) -> None:
    draw_small_text(rgb, text, center_x - small_text_width(text, scale) // 2, y, color, scale)


def draw_right_small_text(rgb, text: str, right_x: int, y: int, color: tuple[int, int, int], scale: int) -> None:
    draw_small_text(rgb, text, right_x - small_text_width(text, scale), y, color, scale)


def existing_output_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.exists():
        return None
    return path


def checked_run_dir(run_dir: Path) -> Path:
    root = PREPROCESSED_DIR.resolve()
    target = Path(run_dir).resolve()
    if root == target or root not in target.parents:
        raise ValueError(f"Refusing to read results outside preprocessing output folder: {target}")
    if not target.exists():
        raise FileNotFoundError(f"Preprocessing run does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Preprocessing run is not a folder: {target}")
    return target


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"


def parse_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
