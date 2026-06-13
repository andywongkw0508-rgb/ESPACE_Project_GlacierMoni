from __future__ import annotations

import csv
import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
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
    cloud_mask: bool = False,
    progress: ProgressCallback | None = None,
) -> PreprocessResult:
    if not rows:
        raise ValueError("No scenes were provided for preprocessing.")

    aoi = load_aoi()
    PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    mask_tag = "_cloudmask" if cloud_mask else ""
    run_dir = PREPROCESSED_DIR / f"run_{timestamp}_s2{sentinel_resolution}m{mask_tag}"
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
                "cloud_masked",
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
                writer.writerow(row_result(row, "", "", "", "", cloud_mask, "missing", "No downloaded band files found."))
                log_handle.write(f"{scene_id}: no downloaded band files found.\n")
                continue

            scene_outputs: list[tuple[str, Path]] = []
            for check in checks:
                band_label = str(check["label"])
                source = Path(str(check["matched_path"]))
                output = scene_dir / f"{scene_label}_{safe_name(band_label)}_preprocessed.tif"
                resolution = scene_resolution(row, sentinel_resolution)
                log_handle.write(
                    f"warp {source} -> {output} "
                    f"[dstSRS={PREPROCESS_TARGET_CRS} res={resolution}m "
                    f"bounds=({aoi['west']},{aoi['south']},{aoi['east']},{aoi['north']}) "
                    f"cloud_mask={cloud_mask}]\n"
                )
                try:
                    gdal_warp(source, output, row, band_label, aoi, sentinel_resolution)
                    raster_count += 1
                    scene_outputs.append((band_label, output))
                    writer.writerow(row_result(row, band_label, resolution, source, output, cloud_mask, "ok", ""))
                    emit(progress, f"Created {output.name}")
                except Exception as exc:
                    message = str(exc)
                    writer.writerow(row_result(row, band_label, resolution, source, output, cloud_mask, "failed", message))
                    log_handle.write(f"FAILED {scene_id} {band_label}: {message}\n")

            if cloud_mask and scene_outputs:
                try:
                    masked_count = apply_cloud_mask_to_scene(row, scene_outputs)
                    emit(progress, f"Applied cloud mask to {masked_count} raster(s) for {scene_id}")
                    log_handle.write(f"{scene_id}: cloud mask applied to {masked_count} raster(s).\n")
                except Exception as exc:
                    log_handle.write(f"FAILED {scene_id} cloud mask: {exc}\n")

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
        multithread=True,
        warpOptions=["NUM_THREADS=ALL_CPUS"],
        creationOptions=["COMPRESS=LZW", "PREDICTOR=2", "TILED=YES"],
    )
    ds = gdal.Warp(str(output), str(source), options=options)
    if ds is None or not output.exists():
        raise RuntimeError(f"gdal.Warp produced no output for {source.name}")
    ds = None


def apply_cloud_mask_to_scene(row: dict[str, str], outputs: list[tuple[str, Path]]) -> int:
    qa = quality_mask_for_scene(row, outputs)
    if qa is None:
        return 0

    mask_array, qa_label = qa
    masked_count = 0
    for band_label, path in outputs:
        if is_quality_band(band_label):
            continue
        apply_mask_to_raster(path, mask_array, qa_label)
        masked_count += 1
    return masked_count


def quality_mask_for_scene(row: dict[str, str], outputs: list[tuple[str, Path]]) -> tuple[np.ndarray, str] | None:
    if row.get("sensor") == "sentinel-2-l2a":
        for band_label, path in outputs:
            if band_label.lower() == "scl":
                ds = open_raster(path)
                scl = ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
                return sentinel_cloud_mask(scl), band_label
    if row.get("sensor") == "landsat-c2-l2":
        for band_label, path in outputs:
            if band_label.lower() == "qa pixel":
                ds = open_raster(path)
                qa = ds.GetRasterBand(1).ReadAsArray().astype(np.uint16)
                return landsat_cloud_mask(qa), band_label
    return None


def sentinel_cloud_mask(scl: np.ndarray) -> np.ndarray:
    # SCL classes removed: no data, saturated/defective, dark/shadow, cloud shadow,
    # medium/high cloud probability, and cirrus. Snow/ice is intentionally kept.
    invalid_classes = {0, 1, 2, 3, 8, 9, 10}
    mask = np.zeros(scl.shape, dtype=bool)
    for value in invalid_classes:
        mask |= scl == value
    return mask


def landsat_cloud_mask(qa: np.ndarray) -> np.ndarray:
    # Collection 2 QA_PIXEL bits: fill, dilated cloud, cirrus, cloud, cloud shadow.
    invalid_bits = [0, 1, 2, 3, 4]
    mask = np.zeros(qa.shape, dtype=bool)
    for bit in invalid_bits:
        mask |= (qa & (1 << bit)) != 0
    return mask


def apply_mask_to_raster(path: Path, cloud_mask: np.ndarray, qa_label: str) -> None:
    ds = gdal.Open(str(path), gdal.GA_Update)
    if ds is None:
        raise RuntimeError(f"Could not open raster for cloud masking: {path}")
    if ds.RasterYSize != cloud_mask.shape[0] or ds.RasterXSize != cloud_mask.shape[1]:
        raise RuntimeError(f"{qa_label} grid does not match raster grid for cloud masking: {path.name}")

    for band_index in range(1, ds.RasterCount + 1):
        band = ds.GetRasterBand(band_index)
        array = band.ReadAsArray()
        nodata = nodata_for_array(array)
        array = array.copy()
        array[cloud_mask] = nodata
        band.WriteArray(array)
        band.SetNoDataValue(float(nodata))
    ds.FlushCache()
    ds = None


def nodata_for_array(array: np.ndarray) -> int | float:
    if np.issubdtype(array.dtype, np.floating):
        return -9999.0
    if np.issubdtype(array.dtype, np.unsignedinteger):
        return 0
    return -9999


def open_raster(path: Path) -> gdal.Dataset:
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"Could not open raster: {path}")
    return ds


def is_quality_band(label: str) -> bool:
    return label.lower() in {"scl", "qa pixel"}


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
    cloud_masked: bool,
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
        "cloud_masked": "yes" if cloud_masked else "no",
        "status": status,
        "message": message,
    }


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"


def emit(progress: ProgressCallback | None, message: str) -> None:
    if progress:
        progress(message)
