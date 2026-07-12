from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from osgeo import gdal

try:
    from .config import PREPROCESSED_DIR
    from .result_exports import publish_index
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import PREPROCESSED_DIR
    from glacier_app.result_exports import publish_index


ProgressCallback = Callable[[str], None]

INDEX_NODATA = -9999.0
CHL_WATER_NDWI_THRESHOLD = 0.0
CHL_A_METHOD = "oc4v4_blue_green_chlorophyll_a"
# SeaWiFS OC4v4 coefficients cited from O'Reilly et al. (1998), doi:10.1029/98JC02160.
# Full OC4 uses the maximum of several blue bands over green; this app applies the cited
# polynomial to the available blue/green pair, so the product remains a CHL-A proxy.
CHL_A_OC4V4_COEFFICIENTS = (0.366, -3.067, 1.930, 0.649, -1.532)
TURBIDITY_WATER_NDWI_THRESHOLD = 0.05
TURBIDITY_SNOW_NDSI_THRESHOLD = 0.40
TURBIDITY_LOW_PERCENTILE = 5.0
TURBIDITY_HIGH_PERCENTILE = 98.0
TURBIDITY_WARNING_SCORE_THRESHOLD = 0.65
INDEX_MANIFEST_FIELDS = [
    "scene_id",
    "date",
    "sensor",
    "index",
    "formula",
    "first_band",
    "second_band",
    "first_file",
    "second_file",
    "output_file",
    "status",
    "message",
]


@dataclass(frozen=True)
class IndexSpec:
    name: str
    first_role: str
    second_role: str
    formula_label: str
    method: str = "normalized_difference"


@dataclass
class BandInput:
    label: str
    path: Path


@dataclass
class SceneInput:
    scene_id: str
    date: str
    sensor: str
    bands: dict[str, BandInput] = field(default_factory=dict)


@dataclass
class IndexResult:
    run_dir: Path
    scene_count: int
    index_count: int
    output_manifest: Path
    log_file: Path


INDEX_SPECS = [
    IndexSpec("NDSI", "green", "swir", "(Green - SWIR) / (Green + SWIR)"),
    IndexSpec("NDWI", "green", "nir", "(Green - NIR) / (Green + NIR)"),
    IndexSpec("NDTI", "red", "green", "(Red - Green) / (Red + Green); turbidity proxy"),
    IndexSpec(
        "TURBIDITY",
        "red",
        "green",
        "Adaptive visible-water turbidity score; SCL/QA water mask preferred, NDWI+NDSI fallback",
        "glacial_turbidity",
    ),
    IndexSpec(
        "CHL_A",
        "blue",
        "green",
        "SeaWiFS OC4v4 coefficients applied to blue/green ratio; SCL/QA water mask preferred",
        CHL_A_METHOD,
    ),
    IndexSpec(
        "CHL_TURBIDITY_WARNING",
        "red",
        "green",
        "Water-only pixels where turbidity score >= 0.65; CHL-A may be sediment-biased",
        "chl_turbidity_warning",
    ),
    IndexSpec("NDCI", "red_edge", "red", "(Red Edge - Red) / (Red Edge + Red)"),
]

BAND_ROLES = {
    "blue": "blue",
    "blue b02": "blue",
    "green": "green",
    "green b03": "green",
    "red": "red",
    "red b04": "red",
    "red edge b05": "red_edge",
    "red-edge b05": "red_edge",
    "rededge b05": "red_edge",
    "nir": "nir",
    "nir b08": "nir",
    "nir08": "nir",
    "swir": "swir",
    "swir b11": "swir",
    "swir16": "swir",
    "scl": "quality",
    "qa pixel": "quality",
}


def calculate_run_indexes(
    run_dir: Path,
    progress: ProgressCallback | None = None,
    index_names: list[str] | tuple[str, ...] | set[str] | None = None,
) -> IndexResult:
    run_dir = checked_run_dir(run_dir)
    preprocessed_manifest = run_dir / "preprocessed_manifest.csv"
    if not preprocessed_manifest.exists():
        raise FileNotFoundError(f"Missing preprocessing manifest: {preprocessed_manifest}")

    scenes = read_preprocessed_scenes(preprocessed_manifest)
    output_root = run_dir / "indexes"
    output_root.mkdir(parents=True, exist_ok=True)
    output_manifest = run_dir / "index_manifest.csv"
    log_file = run_dir / "index_calculation.log"

    selected_names = {name.upper() for name in index_names} if index_names else None
    specs = [spec for spec in INDEX_SPECS if selected_names is None or spec.name.upper() in selected_names]
    preserved_rows = preserved_manifest_rows(output_manifest, selected_names)

    index_count = 0
    with output_manifest.open("w", newline="", encoding="utf-8") as manifest_handle, log_file.open(
        "w", encoding="utf-8"
    ) as log_handle:
        writer = csv.DictWriter(
            manifest_handle,
            fieldnames=INDEX_MANIFEST_FIELDS,
        )
        writer.writeheader()
        writer.writerows(preserved_rows)

        for scene_index, scene in enumerate(scenes.values(), start=1):
            scene_dir = output_root / safe_name(scene.scene_id)
            scene_dir.mkdir(parents=True, exist_ok=True)
            for spec in specs:
                first = scene.bands.get(spec.first_role)
                second = scene.bands.get(spec.second_role)
                water_mask_band = None
                water_mask_kind = ""
                aux_mask_band = None
                aux_mask_kind = ""
                if spec.method == CHL_A_METHOD:
                    water_mask_band = scene.bands.get("quality") or scene.bands.get("nir")
                    water_mask_kind = "quality" if scene.bands.get("quality") else "ndwi"
                elif spec.method in {"glacial_turbidity", "chl_turbidity_warning"}:
                    water_mask_band = scene.bands.get("quality") or scene.bands.get("nir")
                    water_mask_kind = "quality" if scene.bands.get("quality") else "spectral_water"
                    if water_mask_kind == "spectral_water":
                        aux_mask_band = scene.bands.get("swir")
                        aux_mask_kind = "swir"
                output = scene_dir / f"{safe_name(scene.scene_id)}_{spec.name}.tif"
                missing = missing_roles(scene, spec)
                if spec.method in {CHL_A_METHOD, "glacial_turbidity", "chl_turbidity_warning"} and water_mask_band is None:
                    missing = append_missing(missing, "NIR or SCL/QA water mask")
                if missing:
                    writer.writerow(index_row(scene, spec, first, second, output, "missing", missing))
                    log_handle.write(f"{scene.scene_id} {spec.name}: missing {missing}\n")
                    continue

                emit(progress, f"Calculating {spec.name} for scene {scene_index}/{len(scenes)}: {scene.scene_id}")
                try:
                    compute_index_raster(
                        first.path,
                        second.path,
                        output,
                        spec.method,
                        water_mask_band.path if water_mask_band else None,
                        water_mask_kind,
                        scene.sensor,
                        aux_mask_band.path if aux_mask_band else None,
                        aux_mask_kind,
                    )
                    publish_index(output, spec.name, scene.date, scene.scene_id)
                    index_count += 1
                    writer.writerow(index_row(scene, spec, first, second, output, "ok", ""))
                    emit(progress, f"Created {output.name}")
                except Exception as exc:
                    message = str(exc)
                    writer.writerow(index_row(scene, spec, first, second, output, "failed", message))
                    log_handle.write(f"FAILED {scene.scene_id} {spec.name}: {message}\n")

    emit(progress, f"Index calculation complete: {index_count} rasters written.")
    return IndexResult(
        run_dir=run_dir,
        scene_count=len(scenes),
        index_count=index_count,
        output_manifest=output_manifest,
        log_file=log_file,
    )


def read_preprocessed_scenes(manifest_path: Path) -> dict[str, SceneInput]:
    scenes: dict[str, SceneInput] = {}
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            role = band_role(row.get("band", ""))
            if not role:
                continue
            output_value = row.get("output_file", "")
            if not output_value:
                continue
            output_file = Path(output_value)
            if not output_file.exists():
                continue
            scene_id = row.get("scene_id", "")
            scene = scenes.setdefault(
                scene_id,
                SceneInput(
                    scene_id=scene_id,
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                ),
            )
            scene.bands[role] = BandInput(label=row.get("band", ""), path=output_file)
    return scenes


def preserved_manifest_rows(manifest_path: Path, selected_names: set[str] | None) -> list[dict[str, str]]:
    if selected_names is None or not manifest_path.exists():
        return []
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        return [
            {field: row.get(field, "") for field in INDEX_MANIFEST_FIELDS}
            for row in csv.DictReader(handle)
            if row.get("index", "").upper() not in selected_names
        ]


def checked_run_dir(run_dir: Path) -> Path:
    root = PREPROCESSED_DIR.resolve()
    target = Path(run_dir).resolve()
    if root == target or root not in target.parents:
        raise ValueError(f"Refusing to write indexes outside preprocessing output folder: {target}")
    if not target.exists():
        raise FileNotFoundError(f"Preprocessing run does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Preprocessing run is not a folder: {target}")
    return target


def compute_index_raster(
    first_file: Path,
    second_file: Path,
    output_file: Path,
    method: str = "normalized_difference",
    mask_file: Path | None = None,
    mask_kind: str = "",
    sensor: str = "",
    aux_file: Path | None = None,
    aux_kind: str = "",
) -> None:
    gdal.UseExceptions()
    ds_a = gdal.Open(str(first_file))
    ds_b = gdal.Open(str(second_file))
    if ds_a is None:
        raise RuntimeError(f"Could not open raster: {first_file}")
    if ds_b is None:
        raise RuntimeError(f"Could not open raster: {second_file}")

    band_a = ds_a.GetRasterBand(1)
    band_b = ds_b.GetRasterBand(1)
    a = band_a.ReadAsArray().astype(np.float32)
    b = band_b.ReadAsArray().astype(np.float32)

    nodata_a = band_a.GetNoDataValue()
    nodata_b = band_b.GetNoDataValue()
    invalid = np.zeros(a.shape, dtype=bool)
    if nodata_a is not None:
        invalid |= np.isclose(a, np.float32(nodata_a))
    if nodata_b is not None:
        invalid |= np.isclose(b, np.float32(nodata_b))
    if method in {CHL_A_METHOD, "glacial_turbidity", "chl_turbidity_warning"}:
        water_mask = None
        if mask_file is not None:
            if mask_kind == "quality":
                water_mask, mask_invalid = read_quality_water_mask(mask_file, ds_a, sensor)
            else:
                nir, mask_invalid = read_matching_mask_array(mask_file, ds_a)
                if method in {"glacial_turbidity", "chl_turbidity_warning"}:
                    swir = None
                    if aux_file is not None and aux_kind == "swir":
                        swir, aux_invalid = read_matching_mask_array(aux_file, ds_a)
                        mask_invalid |= aux_invalid
                    water_mask = spectral_turbidity_water_mask(b, nir, swir)
                else:
                    water_mask = ndwi_water_mask(b, nir, CHL_WATER_NDWI_THRESHOLD)
            invalid |= mask_invalid
        if method == CHL_A_METHOD:
            result = compute_chlorophyll_a(a, b, invalid, water_mask)
        elif method == "glacial_turbidity":
            result = compute_glacial_turbidity(a, b, invalid, water_mask)
        else:
            result = compute_chl_turbidity_warning(a, b, invalid, water_mask)
    else:
        denom = a + b
        invalid |= (denom == 0)
        safe_denom = np.where(invalid, np.float32(1.0), denom)
        result = np.where(invalid, INDEX_NODATA, (a - b) / safe_denom).astype(np.float32)

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(
        str(output_file),
        ds_a.RasterXSize,
        ds_a.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW", "PREDICTOR=3", "TILED=YES"],
    )
    if out_ds is None:
        raise RuntimeError(f"Could not create output raster: {output_file}")
    out_ds.SetGeoTransform(ds_a.GetGeoTransform())
    out_ds.SetProjection(ds_a.GetProjection())
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(INDEX_NODATA)
    out_band.WriteArray(result)
    out_ds.FlushCache()
    out_ds = None
    ds_a = None
    ds_b = None


def read_matching_mask_array(mask_file: Path, reference_ds: gdal.Dataset) -> tuple[np.ndarray, np.ndarray]:
    ds = gdal.Open(str(mask_file))
    if ds is None:
        raise RuntimeError(f"Could not open water-mask raster: {mask_file}")
    if ds.RasterXSize != reference_ds.RasterXSize or ds.RasterYSize != reference_ds.RasterYSize:
        raise RuntimeError(f"Water-mask raster grid does not match index raster: {mask_file}")
    band = ds.GetRasterBand(1)
    values = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    invalid = np.zeros(values.shape, dtype=bool)
    if nodata is not None:
        invalid |= np.isclose(values, np.float32(nodata))
    ds = None
    return values, invalid


def read_quality_water_mask(
    mask_file: Path,
    reference_ds: gdal.Dataset,
    sensor: str,
) -> tuple[np.ndarray, np.ndarray]:
    values, invalid = read_matching_mask_array(mask_file, reference_ds)
    if sensor == "sentinel-2-l2a":
        return values.astype(np.uint8) == 6, invalid
    if sensor == "landsat-c2-l2":
        return (values.astype(np.uint16) & (1 << 7)) != 0, invalid
    return np.zeros(values.shape, dtype=bool), invalid


def ndwi_water_mask(green: np.ndarray, nir: np.ndarray, threshold: float = CHL_WATER_NDWI_THRESHOLD) -> np.ndarray:
    denom = green + nir
    valid = denom != 0
    safe_denom = np.where(valid, denom, np.float32(1.0))
    ndwi = (green - nir) / safe_denom
    return valid & (ndwi >= np.float32(threshold))


def spectral_turbidity_water_mask(
    green: np.ndarray,
    nir: np.ndarray,
    swir: np.ndarray | None,
) -> np.ndarray:
    water = ndwi_water_mask(green, nir, TURBIDITY_WATER_NDWI_THRESHOLD)
    if swir is None:
        return water

    snow_denom = green + swir
    snow_valid = np.isfinite(green) & np.isfinite(nir) & np.isfinite(swir) & (snow_denom != 0)
    snow_index = np.zeros(green.shape, dtype=np.float32)
    snow_index[snow_valid] = (green[snow_valid] - swir[snow_valid]) / snow_denom[snow_valid]

    candidate_nir = nir[water & np.isfinite(nir)]
    if candidate_nir.size:
        bright_nir_limit = float(np.percentile(candidate_nir, 80.0))
    else:
        bright_nir_limit = float("inf")
    snow_or_ice = (
        snow_valid
        & (snow_index >= np.float32(TURBIDITY_SNOW_NDSI_THRESHOLD))
        & (nir >= np.float32(bright_nir_limit))
    )
    return water & ~snow_or_ice


def compute_chlorophyll_a(
    blue: np.ndarray,
    green: np.ndarray,
    invalid: np.ndarray,
    water_mask: np.ndarray | None,
) -> np.ndarray:
    invalid = invalid | (blue <= 0) | (green <= 0)
    if water_mask is not None:
        invalid |= ~water_mask
    safe_blue = np.where(invalid, np.float32(1.0), blue)
    safe_green = np.where(invalid, np.float32(1.0), green)

    ratio = np.clip(safe_blue / safe_green, np.float32(0.01), np.float32(100.0))
    r = np.log10(ratio)
    a0, a1, a2, a3, a4 = (np.float32(value) for value in CHL_A_OC4V4_COEFFICIENTS)
    log_chla = (
        a0
        + a1 * r
        + a2 * r**2
        + a3 * r**3
        + a4 * r**4
    )
    chlorophyll = np.power(np.float32(10.0), log_chla)
    chlorophyll = np.clip(chlorophyll, np.float32(0.0), np.float32(1000.0))
    return np.where(invalid, INDEX_NODATA, chlorophyll).astype(np.float32)


def compute_chl_turbidity_warning(
    red: np.ndarray,
    green: np.ndarray,
    invalid: np.ndarray,
    water_mask: np.ndarray | None,
) -> np.ndarray:
    turbidity = compute_glacial_turbidity(red, green, invalid, water_mask)
    valid = turbidity != np.float32(INDEX_NODATA)
    warnings = valid & (turbidity >= np.float32(TURBIDITY_WARNING_SCORE_THRESHOLD))
    result = np.full(red.shape, INDEX_NODATA, dtype=np.float32)
    result[valid] = np.float32(0.0)
    result[warnings] = np.float32(1.0)
    return result


def compute_glacial_turbidity(
    red: np.ndarray,
    green: np.ndarray,
    invalid: np.ndarray,
    water_mask: np.ndarray | None,
) -> np.ndarray:
    denom = red + green
    invalid = invalid | ~np.isfinite(red) | ~np.isfinite(green) | (red <= 0) | (green <= 0) | (denom == 0)
    if water_mask is not None:
        invalid |= ~water_mask
    valid = ~invalid
    visible_brightness = np.float32(0.55) * red + np.float32(0.45) * green
    ndti = (red - green) / np.where(valid, denom, np.float32(1.0))
    brightness_score = percentile_scaled(visible_brightness, valid)
    ndti_score = percentile_scaled(ndti, valid)
    score = np.clip(np.float32(0.82) * brightness_score + np.float32(0.18) * ndti_score, 0.0, 1.0)
    result = np.where(valid, score, np.float32(INDEX_NODATA)).astype(np.float32)
    return result


def percentile_scaled(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    scaled = np.zeros(values.shape, dtype=np.float32)
    valid_values = values[valid & np.isfinite(values)]
    if valid_values.size == 0:
        return scaled
    low = float(np.percentile(valid_values, TURBIDITY_LOW_PERCENTILE))
    high = float(np.percentile(valid_values, TURBIDITY_HIGH_PERCENTILE))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(valid_values))
        high = float(np.max(valid_values))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return scaled
    scaled_values = (values - np.float32(low)) / np.float32(high - low)
    scaled[valid] = np.clip(scaled_values[valid], 0.0, 1.0)
    return scaled


def band_role(label: str) -> str:
    return BAND_ROLES.get(label.strip().lower(), "")


def missing_roles(scene: SceneInput, spec: IndexSpec) -> str:
    missing = []
    if spec.first_role not in scene.bands:
        missing.append(spec.first_role)
    if spec.second_role not in scene.bands:
        missing.append(spec.second_role)
    return ", ".join(missing)


def append_missing(existing: str, item: str) -> str:
    if not existing:
        return item
    return f"{existing}, {item}"


def index_row(
    scene: SceneInput,
    spec: IndexSpec,
    first: BandInput | None,
    second: BandInput | None,
    output: Path,
    status: str,
    message: str,
) -> dict[str, str]:
    return {
        "scene_id": scene.scene_id,
        "date": scene.date,
        "sensor": scene.sensor,
        "index": spec.name,
        "formula": spec.formula_label,
        "first_band": first.label if first else "",
        "second_band": second.label if second else "",
        "first_file": str(first.path) if first else "",
        "second_file": str(second.path) if second else "",
        "output_file": str(output),
        "status": status,
        "message": message,
    }


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"


def emit(progress: ProgressCallback | None, message: str) -> None:
    if progress:
        progress(message)
