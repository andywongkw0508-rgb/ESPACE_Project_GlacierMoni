from __future__ import annotations

import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(APP_DIR / ".env")

DATA_ROOT = Path(os.environ.get("GLACIER_DATA_ROOT", PROJECT_ROOT / "data" / "vatnajokull_28WDS_by_band"))
MANIFEST = DATA_ROOT / "master_manifest.csv"

BAND_PREVIEW_CACHE = APP_DIR / "outputs" / "band_previews"
AOI_CONFIG = APP_DIR / "config" / "aoi.json"
PREPROCESSED_DIR = APP_DIR / "outputs" / "preprocessed"
RESULTS_DIR = APP_DIR / "outputs" / "results"
DEFAULT_PREVIEW_SCENE_ID = "S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234"
OVERLAY_BASE_SCENE_ID = DEFAULT_PREVIEW_SCENE_ID
PREPROCESS_TARGET_CRS = "EPSG:32628"
SENTINEL_PREPROCESS_RESOLUTIONS = ["10", "20", "30"]
DEFAULT_SENTINEL_PREPROCESS_RESOLUTION = "30"
LANDSAT_PREPROCESS_RESOLUTION = "30"

SENTINEL_BANDS = [
    ("visual", "Visual", "raw_visual_url"),
    ("blue_B02", "Blue B02", "raw_blue_B02_url"),
    ("green_B03", "Green B03", "raw_green_B03_url"),
    ("red_B04", "Red B04", "raw_red_B04_url"),
    ("red_edge_B05", "Red Edge B05", "raw_red_edge_B05_url"),
    ("nir_B08", "NIR B08", "raw_nir_B08_url"),
    ("swir_B11", "SWIR B11", "raw_swir_B11_url"),
    ("scene_classification_SCL", "SCL", "raw_scene_classification_SCL_url"),
]

LANDSAT_BANDS = [
    ("blue", "Blue", "raw_blue_url"),
    ("green", "Green", "raw_green_url"),
    ("red", "Red", "raw_red_url"),
    ("nir08", "NIR08", "raw_nir08_url"),
    ("swir16", "SWIR16", "raw_swir16_url"),
    ("qa_pixel", "QA Pixel", "raw_qa_pixel_url"),
]
