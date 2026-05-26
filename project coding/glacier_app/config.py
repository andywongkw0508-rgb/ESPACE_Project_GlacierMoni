from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent
DATA_ROOT = PROJECT_ROOT / "data" / "vatnajokull_28WDS_by_band"
MANIFEST = DATA_ROOT / "master_manifest.csv"
GDAL_TRANSLATE = Path("C:/Program Files/QGIS 4.0.2/bin/gdal_translate.exe")
BAND_PREVIEW_CACHE = APP_DIR / "outputs" / "band_previews"

SENTINEL_BANDS = [
    ("visual", "Visual", "raw_visual_url"),
    ("blue_B02", "Blue B02", "raw_blue_B02_url"),
    ("green_B03", "Green B03", "raw_green_B03_url"),
    ("red_B04", "Red B04", "raw_red_B04_url"),
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
