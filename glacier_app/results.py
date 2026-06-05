from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from osgeo import gdal

try:
    from .config import BAND_PREVIEW_CACHE, PREPROCESSED_DIR
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import BAND_PREVIEW_CACHE, PREPROCESSED_DIR


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
            outputs.append(
                ProcessingOutput(
                    run_name=run_dir.name,
                    kind="Boundary",
                    label=f"{row.get('source_mask', '')} Boundary".strip(),
                    scene_id=row.get("scene_id", ""),
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                    formula=f"Boundary of {row.get('source_formula', '')}".strip(),
                    output_file=output_file,
                    pixel_count=parse_int(row.get("boundary_pixels", "")),
                    area_km2=parse_float(row.get("boundary_length_km", "")),
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
                )
            )
    return outputs


def processing_preview_png(output: ProcessingOutput) -> Path:
    source = output.output_file
    cache_dir = BAND_PREVIEW_CACHE / "processing_results"
    cache_dir.mkdir(parents=True, exist_ok=True)
    preview_path = cache_dir / f"{source.stem}_{safe_name(output.kind)}_{safe_name(output.label)}.png"
    if preview_path.exists() and preview_path.stat().st_mtime >= source.stat().st_mtime:
        return preview_path

    if output.kind == "Index":
        scale_args = ["-scale", "-1", "1", "0", "255"]
    elif output.kind in {"Mask", "Boundary"}:
        scale_args = ["-scale", "0", "1", "0", "255"]
    else:
        scale_args = ["-scale"]

    gdal.UseExceptions()
    opts = gdal.TranslateOptions(options=["-ot", "Byte", "-outsize", "1600", "0"] + scale_args)
    ds = gdal.Translate(str(preview_path), str(source), options=opts)
    if ds is None or not preview_path.exists():
        raise RuntimeError(f"Could not render {output.label} preview")
    ds = None
    return preview_path


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
