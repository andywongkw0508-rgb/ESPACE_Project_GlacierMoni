from __future__ import annotations

from pathlib import Path

from osgeo import gdal

from .config import BAND_PREVIEW_CACHE, DATA_ROOT, LANDSAT_BANDS, SENTINEL_BANDS


def available_band_labels(row: dict[str, str]) -> list[str]:
    labels = []
    band_columns = {
        "raw_visual_url": "visual",
        "raw_blue_B02_url": "Sentinel blue B02",
        "raw_green_B03_url": "Sentinel green B03",
        "raw_red_B04_url": "Sentinel red B04",
        "raw_nir_B08_url": "Sentinel NIR B08",
        "raw_swir_B11_url": "Sentinel SWIR B11",
        "raw_scene_classification_SCL_url": "Sentinel SCL",
        "raw_blue_url": "Landsat blue",
        "raw_green_url": "Landsat green",
        "raw_red_url": "Landsat red",
        "raw_nir08_url": "Landsat NIR",
        "raw_swir16_url": "Landsat SWIR",
        "raw_qa_pixel_url": "Landsat QA pixel",
    }
    for column, label in band_columns.items():
        if row.get(column):
            labels.append(label)
    return labels or ["No raw assets listed"]


def check_scene_bands(row: dict[str, str]) -> list[dict[str, object]]:
    sensor = row.get("sensor", "")
    year = row.get("year", "")
    if sensor == "sentinel-2-l2a":
        sensor_folder = "sentinel"
        band_specs = SENTINEL_BANDS
    elif sensor == "landsat-c2-l2":
        sensor_folder = "landsat"
        band_specs = LANDSAT_BANDS
    else:
        return []

    checks = []
    file_patterns = scene_file_patterns(row)
    for folder, label, manifest_column in band_specs:
        band_dir = DATA_ROOT / sensor_folder / folder / year
        matches = []
        if band_dir.exists():
            for pattern in file_patterns:
                matches = sorted(band_dir.glob(pattern))
                if matches:
                    break
        matched_file = matches[0].name if matches else ""
        matched_path = str(matches[0]) if matches else ""
        checks.append(
            {
                "label": label,
                "disk_exists": bool(matches),
                "manifest_url": bool(row.get(manifest_column, "")),
                "matched_file": matched_file,
                "matched_path": matched_path,
            }
        )
    return checks


def scene_file_patterns(row: dict[str, str]) -> list[str]:
    item_id = row.get("item_id", "")
    date = row.get("date", "")
    patterns = [f"*{item_id}*.tif"] if item_id else []

    parts = item_id.split("_")
    if row.get("sensor") == "sentinel-2-l2a" and len(parts) >= 5:
        platform = parts[0]
        acquisition = parts[2]
        orbit = parts[3]
        tile = parts[4]
        patterns.append(f"{date}_{platform}_MSIL2A_{acquisition}_{orbit}_{tile}_*.tif")
    elif row.get("sensor") == "landsat-c2-l2" and len(parts) >= 6:
        platform = parts[0]
        level = parts[1]
        path_row = parts[2]
        acquisition_date = parts[3]
        collection = parts[4]
        tier = parts[5]
        patterns.append(f"{date}_{platform}_{level}_{path_row}_{acquisition_date}_{collection}_{tier}_*.tif")

    return patterns


def band_preview_png(tif_path: Path, label: str) -> Path:
    BAND_PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(char if char.isalnum() else "_" for char in label).strip("_")
    preview_path = BAND_PREVIEW_CACHE / f"{tif_path.stem}_{safe_label}.png"
    if preview_path.exists() and preview_path.stat().st_mtime >= tif_path.stat().st_mtime:
        return preview_path

    gdal.UseExceptions()
    opts = gdal.TranslateOptions(options=["-ot", "Byte", "-outsize", "1600", "0", "-scale"])
    ds = gdal.Translate(str(preview_path), str(tif_path), options=opts)
    if ds is None or not preview_path.exists():
        raise RuntimeError(f"Could not render {label} preview")
    ds = None
    return preview_path
