from __future__ import annotations

import csv
import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from osgeo import gdal

try:
    from .bands import check_scene_bands
    from .config import AOI_CONFIG, LANDSAT_PREPROCESS_RESOLUTION, PREPROCESS_TARGET_CRS, PREPROCESSED_DIR
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.bands import check_scene_bands
    from glacier_app.config import (
        AOI_CONFIG,
        LANDSAT_PREPROCESS_RESOLUTION,
        PREPROCESS_TARGET_CRS,
        PREPROCESSED_DIR,
    )


ProgressCallback = Callable[[str], None]


@dataclass
class PreprocessResult:
    scene_count: int
    raster_count: int
    run_dir: Path
    output_manifest: Path
    log_file: Path


def preprocess_rows(
    rows: list[dict[str, str]],
    sentinel_resolution: str,
    progress: ProgressCallback | None = None,
) -> PreprocessResult:
    if not rows:
        raise ValueError("No scenes were provided for preprocessing.")

    aoi = load_aoi()
    PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = PREPROCESSED_DIR / f"run_{timestamp}_s2{sentinel_resolution}m"
    run_dir.mkdir(parents=True, exist_ok=False)
    output_manifest = run_dir / "preprocessed_manifest.csv"
    log_file = run_dir / "preprocess.log"

    raster_count = 0
    with output_manifest.open("w", newline="", encoding="utf-8") as manifest_handle, log_file.open(
        "w", encoding="utf-8"
    ) as log_handle:
        writer = csv.DictWriter(
            manifest_handle,
            fieldnames=[
                "scene_id",
                "date",
                "sensor",
                "band",
                "resolution_m",
                "input_file",
                "output_file",
                "status",
                "message",
            ],
        )
        writer.writeheader()

        for scene_index, row in enumerate(rows, start=1):
            scene_id = row.get("item_id", "")
            scene_label = safe_name(scene_id)
            scene_dir = run_dir / scene_label
            scene_dir.mkdir(parents=True, exist_ok=True)
            checks = [check for check in check_scene_bands(row) if check.get("matched_path")]

            emit(progress, f"Preprocessing scene {scene_index}/{len(rows)}: {scene_id}")
            if not checks:
                writer.writerow(row_result(row, "", "", "", "", "missing", "No downloaded band files found."))
                log_handle.write(f"{scene_id}: no downloaded band files found.\n")
                continue

            for check in checks:
                band_label = str(check["label"])
                source = Path(str(check["matched_path"]))
                output = scene_dir / f"{scene_label}_{safe_name(band_label)}_preprocessed.tif"
                resolution = scene_resolution(row, sentinel_resolution)
                log_handle.write(
                    f"warp {source} -> {output} "
                    f"[dstSRS={PREPROCESS_TARGET_CRS} res={resolution}m "
                    f"bounds=({aoi['west']},{aoi['south']},{aoi['east']},{aoi['north']})]\n"
                )
                try:
                    gdal_warp(source, output, row, band_label, aoi, sentinel_resolution)
                    raster_count += 1
                    writer.writerow(row_result(row, band_label, resolution, source, output, "ok", ""))
                    emit(progress, f"Created {output.name}")
                except Exception as exc:
                    message = str(exc)
                    writer.writerow(row_result(row, band_label, resolution, source, output, "failed", message))
                    log_handle.write(f"FAILED {scene_id} {band_label}: {message}\n")

    emit(progress, f"Preprocessing complete: {raster_count} rasters written.")
    return PreprocessResult(
        scene_count=len(rows),
        raster_count=raster_count,
        run_dir=run_dir,
        output_manifest=output_manifest,
        log_file=log_file,
    )


def list_preprocess_runs() -> list[dict[str, object]]:
    PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for run_dir in sorted(PREPROCESSED_DIR.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
        if not run_dir.is_dir():
            continue
        manifest = run_dir / "preprocessed_manifest.csv"
        raster_count = len(list(run_dir.rglob("*.tif")))
        modified = datetime.fromtimestamp(run_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        runs.append(
            {
                "name": run_dir.name,
                "path": run_dir,
                "modified": modified,
                "raster_count": raster_count,
                "has_manifest": manifest.exists(),
            }
        )
    return runs


def delete_preprocess_run(run_dir: Path) -> None:
    root = PREPROCESSED_DIR.resolve()
    target = run_dir.resolve()
    if root == target or root not in target.parents:
        raise ValueError(f"Refusing to delete outside preprocessing output folder: {target}")
    if not target.exists():
        raise FileNotFoundError(f"Preprocessing run does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Preprocessing run is not a folder: {target}")
    shutil.rmtree(target)


def load_aoi() -> dict[str, float]:
    with AOI_CONFIG.open(encoding="utf-8") as handle:
        config = json.load(handle)
    bbox = config["bbox"]
    return {
        "west": float(bbox["west"]),
        "south": float(bbox["south"]),
        "east": float(bbox["east"]),
        "north": float(bbox["north"]),
    }


def gdal_warp(
    source: Path,
    output: Path,
    row: dict[str, str],
    band_label: str,
    aoi: dict[str, float],
    sentinel_resolution: str,
) -> None:
    gdal.UseExceptions()
    resolution = float(scene_resolution(row, sentinel_resolution))
    resampling = "near" if band_label.lower() in {"scl", "qa pixel"} else "bilinear"
    options = gdal.WarpOptions(
        format="GTiff",
        dstSRS=PREPROCESS_TARGET_CRS,
        outputBounds=(aoi["west"], aoi["south"], aoi["east"], aoi["north"]),
        outputBoundsSRS="EPSG:4326",
        xRes=resolution,
        yRes=resolution,
        targetAlignedPixels=True,
        resampleAlg=resampling,
        srcNodata=0,
        dstNodata=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    ds = gdal.Warp(str(output), str(source), options=options)
    if ds is None or not output.exists():
        raise RuntimeError(f"gdal.Warp produced no output for {source.name}")
    ds = None


def scene_resolution(row: dict[str, str], sentinel_resolution: str) -> str:
    if row.get("sensor") == "sentinel-2-l2a":
        return sentinel_resolution
    return LANDSAT_PREPROCESS_RESOLUTION


def row_result(
    row: dict[str, str],
    band: str,
    resolution: str,
    source: Path | str,
    output: Path | str,
    status: str,
    message: str,
) -> dict[str, str]:
    return {
        "scene_id": row.get("item_id", ""),
        "date": row.get("date", ""),
        "sensor": row.get("sensor", ""),
        "band": str(band),
        "resolution_m": str(resolution),
        "input_file": str(source),
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
