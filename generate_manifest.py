"""Scan the local sentinel data directory and write master_manifest.csv.

Usage
-----
    python generate_manifest.py [DATA_ROOT]

DATA_ROOT is the directory that contains the ``sentinel/`` subfolder.
If omitted the script reads GLACIER_DATA_ROOT from the environment (or
from a .env file in the same directory as this script).

The manifest is written to DATA_ROOT/master_manifest.csv.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader (same logic as app.py so the script is self-contained)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    with env_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env()


# ---------------------------------------------------------------------------
# Resolve DATA_ROOT
# ---------------------------------------------------------------------------

def _resolve_data_root() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    env_val = os.environ.get("GLACIER_DATA_ROOT", "")
    if env_val:
        return Path(env_val).resolve()
    sys.exit(
        "Error: DATA_ROOT not set.\n"
        "Either pass it as an argument:  python generate_manifest.py /path/to/data\n"
        "or set GLACIER_DATA_ROOT in your .env file or shell environment."
    )


DATA_ROOT = _resolve_data_root()
SENTINEL_DIR = DATA_ROOT / "sentinel"
OUTPUT = DATA_ROOT / "master_manifest.csv"

# ---------------------------------------------------------------------------
# Band folder → manifest column mapping
# ---------------------------------------------------------------------------

BAND_FOLDERS = {
    "blue_B02": "raw_blue_B02_url",
    "green_B03": "raw_green_B03_url",
    "red_B04": "raw_red_B04_url",
    "nir_B08": "raw_nir_B08_url",
    "swir_B11": "raw_swir_B11_url",
    "scene_classification_SCL": "raw_scene_classification_SCL_url",
    "visual": "raw_visual_url",
}

# e.g. 2025-06-04_S2B_MSIL2A_20250604T125259_R138_T28WDS_20250604T181034_blue_B02.tif
FILENAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_"
    r"(?P<platform>S2[ABC])_MSIL2A_"
    r"(?P<acquisition>\d{8}T\d{6})_"
    r"(?P<orbit>R\d+)_"
    r"(?P<tile>T\w+)_"
    r"(?P<proc>\d{8}T\d{6})"
    r"_.*\.tif$"
)

FIELDNAMES = [
    "item_id",
    "datetime",
    "date",
    "year",
    "sensor",
    "platform",
    "tile_or_path",
    "cloud_cover",
    "preview_file",
    "raw_visual_url",
    "raw_blue_B02_url",
    "raw_green_B03_url",
    "raw_red_B04_url",
    "raw_nir_B08_url",
    "raw_swir_B11_url",
    "raw_scene_classification_SCL_url",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_datetime(acquisition: str) -> str:
    d = acquisition
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}T{d[9:11]}:{d[11:13]}:{d[13:15]}"


def collect_scenes() -> dict[str, dict]:
    scenes: dict[str, dict] = {}
    for band_folder, url_col in BAND_FOLDERS.items():
        band_dir = SENTINEL_DIR / band_folder
        if not band_dir.exists():
            continue
        for year_dir in sorted(band_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for tif in sorted(year_dir.glob("*.tif")):
                m = FILENAME_RE.match(tif.name)
                if not m:
                    continue
                platform = m.group("platform")
                acquisition = m.group("acquisition")
                orbit = m.group("orbit")
                tile = m.group("tile")
                proc = m.group("proc")
                item_id = f"{platform}_MSIL2A_{acquisition}_{orbit}_{tile}_{proc}"
                if item_id not in scenes:
                    scenes[item_id] = {
                        "item_id": item_id,
                        "datetime": _parse_datetime(acquisition),
                        "date": m.group("date"),
                        "year": year_dir.name,
                        "sensor": "sentinel-2-l2a",
                        "platform": platform,
                        "tile_or_path": tile,
                        "cloud_cover": "0.0",
                        "preview_file": "",
                        **{col: "" for col in BAND_FOLDERS.values()},
                    }
                scenes[item_id][url_col] = str(tif)
    return scenes


def attach_previews(scenes: dict[str, dict]) -> None:
    preview_dir = SENTINEL_DIR / "preview"
    if not preview_dir.exists():
        return
    for png in preview_dir.rglob("*.png"):
        stem = png.stem
        if not stem.endswith("_preview"):
            continue
        item_id_candidate = stem[: -len("_preview")]
        if item_id_candidate in scenes:
            scenes[item_id_candidate]["preview_file"] = str(png)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not SENTINEL_DIR.exists():
        sys.exit(
            f"Sentinel directory not found: {SENTINEL_DIR}\n"
            f"Expected layout: DATA_ROOT/sentinel/<band_folder>/<year>/*.tif"
        )

    scenes = collect_scenes()
    if not scenes:
        sys.exit(
            f"No matching TIF files found under {SENTINEL_DIR}\n"
            "Files must match: YYYY-MM-DD_S2X_MSIL2A_..._<band>.tif"
        )

    attach_previews(scenes)

    rows = sorted(scenes.values(), key=lambda r: (r["date"], r["platform"]))
    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written {len(rows)} scene(s) to {OUTPUT}")
    for row in rows:
        bands = sum(1 for col in BAND_FOLDERS.values() if row.get(col))
        preview = "preview" if row["preview_file"] else "no preview"
        print(f"  {row['date']}  {row['item_id']}  bands={bands}  {preview}")


if __name__ == "__main__":
    main()
