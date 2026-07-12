from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from .config import PREPROCESSED_DIR
    from .result_exports import publish_boundary_files
    from .results import ProcessingOutput
    from . import boundary_worker
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import PREPROCESSED_DIR
    from glacier_app.result_exports import publish_boundary_files
    from glacier_app.results import ProcessingOutput
    from glacier_app import boundary_worker


@dataclass
class BoundaryResult:
    run_dir: Path
    output: ProcessingOutput
    source_pixels: int
    refined_pixels: int
    boundary_pixels: int
    polygon_count: int
    source_region_count: int
    removed_region_count: int
    largest_region_share: float
    boundary_count: int
    boundary_length_m: float
    boundary_length_km: float
    polygon_file: Path
    boundary_file: Path
    manifest: Path


def extract_boundary(output: ProcessingOutput) -> BoundaryResult:
    if output.kind != "Mask":
        raise ValueError("Boundaries can currently be extracted from mask rasters.")
    if "NDSI" not in output.label.upper() and "NDSI" not in output.formula.upper():
        raise ValueError("Glacier boundaries must be extracted from an NDSI mask, not a water mask.")
    if not output.output_file.exists():
        raise FileNotFoundError(f"Source mask raster does not exist: {output.output_file}")

    run_dir = run_dir_for_output(output.output_file)
    scene_dir = run_dir / "boundaries" / safe_name(output.scene_id)
    scene_dir.mkdir(parents=True, exist_ok=True)

    base_name = output.output_file.stem.replace("_mask", "")
    boundary_raster = scene_dir / f"{base_name}_boundary.tif"
    polygon_file = scene_dir / f"{base_name}_polygon.geojson"
    boundary_file = scene_dir / f"{base_name}_boundary.geojson"

    stats = run_boundary_script(output.output_file, boundary_raster, polygon_file, boundary_file)
    publish_boundary_files(boundary_raster, polygon_file, boundary_file, output.date, output.scene_id)
    boundary_output = ProcessingOutput(
        run_name=run_dir.name,
        kind="Boundary",
        label=f"{output.label} Boundary",
        scene_id=output.scene_id,
        date=output.date,
        sensor=output.sensor,
        formula=f"Dominant connected exterior boundary of {output.formula or output.label}",
        output_file=boundary_raster,
        pixel_count=int(stats["boundary_pixels"]),
        area_km2=output.area_km2,
    )
    manifest = write_boundary_manifest(run_dir, output, boundary_output, polygon_file, boundary_file, stats)
    return BoundaryResult(
        run_dir=run_dir,
        output=boundary_output,
        source_pixels=int(stats.get("source_pixels", 0)),
        refined_pixels=int(stats.get("refined_pixels", 0)),
        boundary_pixels=int(stats["boundary_pixels"]),
        polygon_count=int(stats["polygon_count"]),
        source_region_count=int(stats.get("source_region_count", stats["polygon_count"])),
        removed_region_count=int(stats.get("removed_region_count", 0)),
        largest_region_share=float(stats.get("largest_region_share", 1.0)),
        boundary_count=int(stats["boundary_count"]),
        boundary_length_m=float(stats["boundary_length_m"]),
        boundary_length_km=float(stats["boundary_length_km"]),
        polygon_file=polygon_file,
        boundary_file=boundary_file,
        manifest=manifest,
    )


def run_boundary_script(
    mask_file: Path,
    boundary_raster: Path,
    polygon_file: Path,
    boundary_file: Path,
) -> dict[str, float | int]:
    try:
        return boundary_worker.compute(
            str(mask_file),
            str(boundary_raster),
            str(polygon_file),
            str(boundary_file),
        )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Boundary extraction failed: {exc}") from exc


def write_boundary_manifest(
    run_dir: Path,
    source: ProcessingOutput,
    boundary: ProcessingOutput,
    polygon_file: Path,
    boundary_file: Path,
    stats: dict[str, float | int],
) -> Path:
    manifest = run_dir / "boundary_manifest.csv"
    fields = [
        "created_at",
        "scene_id",
        "date",
        "sensor",
        "source_mask",
        "source_formula",
        "source_pixels",
        "refined_pixels",
        "boundary_pixels",
        "polygon_count",
        "source_region_count",
        "removed_region_count",
        "largest_region_share",
        "boundary_count",
        "boundary_length_m",
        "boundary_length_km",
        "source_file",
        "output_file",
        "polygon_file",
        "boundary_file",
        "status",
        "message",
    ]
    rows = []
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get("output_file") != str(boundary.output_file)]

    rows.append(
        {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scene_id": source.scene_id,
            "date": source.date,
            "sensor": source.sensor,
            "source_mask": source.label,
            "source_formula": source.formula,
            "source_pixels": str(int(stats.get("source_pixels", 0))),
            "refined_pixels": str(int(stats.get("refined_pixels", 0))),
            "boundary_pixels": str(int(stats["boundary_pixels"])),
            "polygon_count": str(int(stats["polygon_count"])),
            "source_region_count": str(int(stats.get("source_region_count", stats["polygon_count"]))),
            "removed_region_count": str(int(stats.get("removed_region_count", 0))),
            "largest_region_share": f"{float(stats.get('largest_region_share', 1.0)):.6f}",
            "boundary_count": str(int(stats["boundary_count"])),
            "boundary_length_m": f"{float(stats['boundary_length_m']):.6f}",
            "boundary_length_km": f"{float(stats['boundary_length_km']):.6f}",
            "source_file": str(source.output_file),
            "output_file": str(boundary.output_file),
            "polygon_file": str(polygon_file),
            "boundary_file": str(boundary_file),
            "status": "ok",
            "message": "",
        }
    )

    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def run_dir_for_output(output_file: Path) -> Path:
    root = PREPROCESSED_DIR.resolve()
    target = output_file.resolve()
    if root not in target.parents:
        raise ValueError(f"Refusing to write boundary outside preprocessing output folder: {target}")
    relative = target.relative_to(root)
    if not relative.parts:
        raise ValueError(f"Could not identify preprocessing run for output: {target}")
    run_dir = root / relative.parts[0]
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Preprocessing run does not exist: {run_dir}")
    return run_dir


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"
