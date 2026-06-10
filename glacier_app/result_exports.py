from __future__ import annotations

import shutil
from pathlib import Path

from .config import RESULTS_DIR


def publish_index(index_file: Path, index_name: str, date: str, scene_id: str) -> Path:
    year = year_from_date(date)
    return copy_result(index_file, RESULTS_DIR / "indexes" / safe_name(index_name.upper()) / year, scene_id)


def publish_mask(mask_file: Path, source_index: str, date: str, scene_id: str) -> Path:
    year = year_from_date(date)
    return copy_result(mask_file, RESULTS_DIR / "masks" / safe_name(source_index.upper()) / year, scene_id)


def publish_boundary_files(
    boundary_raster: Path,
    polygon_file: Path,
    boundary_file: Path,
    date: str,
    scene_id: str,
) -> dict[str, Path]:
    year = year_from_date(date)
    target_dir = RESULTS_DIR / "boundaries" / year / safe_name(scene_id)
    return {
        "boundary_raster": copy_result(boundary_raster, target_dir, scene_id),
        "polygon_file": copy_result(polygon_file, target_dir, scene_id),
        "boundary_file": copy_result(boundary_file, target_dir, scene_id),
    }


def overlay_dir() -> Path:
    path = RESULTS_DIR / "overlays"
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_result(source: Path, target_dir: Path, scene_id: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_name(scene_id)}_{source.name}"
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def year_from_date(date: str) -> str:
    return date[:4] if len(date) >= 4 and date[:4].isdigit() else "unknown_year"


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"
