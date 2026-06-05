from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from .config import PREPROCESSED_DIR
    from .result_exports import publish_mask
    from .results import ProcessingOutput
    from . import mask_worker
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import PREPROCESSED_DIR
    from glacier_app.result_exports import publish_mask
    from glacier_app.results import ProcessingOutput
    from glacier_app import mask_worker


DEFAULT_MASK_THRESHOLDS = {
    "NDSI": 0.40,
    "NDWI": 0.20,
}


@dataclass
class MaskResult:
    run_dir: Path
    output: ProcessingOutput
    threshold: float
    mask_pixels: int
    valid_pixels: int
    water_excluded_pixels: int
    cloud_excluded_pixels: int
    pixel_area_m2: float
    area_m2: float
    area_km2: float
    manifest: Path


def build_mask(output: ProcessingOutput, threshold: float) -> MaskResult:
    if output.kind != "Index":
        raise ValueError("Masks can currently be built from NDSI or NDWI index rasters.")
    if output.label.upper() not in DEFAULT_MASK_THRESHOLDS:
        raise ValueError("Select an NDSI or NDWI result before building a mask.")
    if not output.output_file.exists():
        raise FileNotFoundError(f"Source result raster does not exist: {output.output_file}")

    run_dir = run_dir_for_output(output.output_file)
    scene_dir = run_dir / "masks" / safe_name(output.scene_id)
    scene_dir.mkdir(parents=True, exist_ok=True)
    threshold_tag = threshold_name(threshold)
    mask_file = scene_dir / f"{safe_name(output.scene_id)}_{safe_name(output.label)}_gte_{threshold_tag}_mask.tif"

    exclusions = exclusion_inputs(run_dir, output)
    stats = run_mask_script(output.output_file, mask_file, threshold, exclusions)
    publish_mask(mask_file, output.label, output.date, output.scene_id)
    formula = f"{output.label} >= {threshold:.3f}"
    if exclusions.water_file:
        formula += f" AND NDWI < {exclusions.water_threshold:.2f}"
    if exclusions.quality_file:
        formula += " AND cloud/water QA excluded"
    mask_output = ProcessingOutput(
        run_name=run_dir.name,
        kind="Mask",
        label=f"{output.label} Mask",
        scene_id=output.scene_id,
        date=output.date,
        sensor=output.sensor,
        formula=formula,
        output_file=mask_file,
        pixel_count=int(stats["mask_pixels"]),
        area_km2=float(stats["area_km2"]),
    )
    manifest = write_mask_manifest(run_dir, output, mask_output, threshold, stats)
    return MaskResult(
        run_dir=run_dir,
        output=mask_output,
        threshold=threshold,
        mask_pixels=int(stats["mask_pixels"]),
        valid_pixels=int(stats["valid_pixels"]),
        water_excluded_pixels=int(stats.get("water_excluded_pixels", 0)),
        cloud_excluded_pixels=int(stats.get("cloud_excluded_pixels", 0)),
        pixel_area_m2=float(stats["pixel_area_m2"]),
        area_m2=float(stats["area_m2"]),
        area_km2=float(stats["area_km2"]),
        manifest=manifest,
    )


def default_threshold_for(output: ProcessingOutput) -> float | None:
    return DEFAULT_MASK_THRESHOLDS.get(output.label.upper())


@dataclass
class ExclusionInputs:
    water_file: Path | None = None
    water_threshold: float = DEFAULT_MASK_THRESHOLDS["NDWI"]
    quality_file: Path | None = None
    sensor: str = ""


def run_mask_script(source: Path, output: Path, threshold: float, exclusions: ExclusionInputs) -> dict[str, float | int]:
    try:
        return mask_worker.compute(
            str(source),
            str(output),
            threshold,
            str(exclusions.water_file or ""),
            exclusions.water_threshold,
            str(exclusions.quality_file or ""),
            exclusions.sensor,
        )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Mask computation failed: {exc}") from exc


def write_mask_manifest(
    run_dir: Path,
    source: ProcessingOutput,
    mask: ProcessingOutput,
    threshold: float,
    stats: dict[str, float | int],
) -> Path:
    manifest = run_dir / "mask_manifest.csv"
    fields = [
        "created_at",
        "scene_id",
        "date",
        "sensor",
        "source_index",
        "threshold",
        "formula",
        "mask_pixels",
        "valid_pixels",
        "water_excluded_pixels",
        "cloud_excluded_pixels",
        "excluded_pixels",
        "pixel_area_m2",
        "area_m2",
        "area_km2",
        "source_file",
        "output_file",
        "status",
        "message",
    ]
    rows = []
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get("output_file") != str(mask.output_file)]

    rows.append(
        {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scene_id": source.scene_id,
            "date": source.date,
            "sensor": source.sensor,
            "source_index": source.label,
            "threshold": f"{threshold:.6f}",
            "formula": mask.formula,
            "mask_pixels": str(int(stats["mask_pixels"])),
            "valid_pixels": str(int(stats["valid_pixels"])),
            "water_excluded_pixels": str(int(stats.get("water_excluded_pixels", 0))),
            "cloud_excluded_pixels": str(int(stats.get("cloud_excluded_pixels", 0))),
            "excluded_pixels": str(int(stats.get("excluded_pixels", 0))),
            "pixel_area_m2": f"{float(stats['pixel_area_m2']):.6f}",
            "area_m2": f"{float(stats['area_m2']):.6f}",
            "area_km2": f"{float(stats['area_km2']):.6f}",
            "source_file": str(source.output_file),
            "output_file": str(mask.output_file),
            "status": "ok",
            "message": "",
        }
    )

    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def exclusion_inputs(run_dir: Path, output: ProcessingOutput) -> ExclusionInputs:
    if output.label.upper() != "NDSI":
        return ExclusionInputs(sensor=output.sensor)
    return ExclusionInputs(
        water_file=matching_index_file(run_dir, output.scene_id, "NDWI"),
        quality_file=matching_quality_file(run_dir, output.scene_id, output.sensor),
        sensor=output.sensor,
    )


def matching_index_file(run_dir: Path, scene_id: str, index_name: str) -> Path | None:
    manifest = run_dir / "index_manifest.csv"
    if not manifest.exists():
        return None
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "ok":
                continue
            if row.get("scene_id", "") != scene_id or row.get("index", "").upper() != index_name:
                continue
            path = Path(row.get("output_file", ""))
            if path.exists():
                return path
    return None


def matching_quality_file(run_dir: Path, scene_id: str, sensor: str) -> Path | None:
    manifest = run_dir / "preprocessed_manifest.csv"
    if not manifest.exists():
        return None
    wanted = "SCL" if sensor == "sentinel-2-l2a" else "QA Pixel"
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "ok":
                continue
            if row.get("scene_id", "") != scene_id or row.get("band", "") != wanted:
                continue
            path = Path(row.get("output_file", ""))
            if path.exists():
                return path
    return None


def run_dir_for_output(output_file: Path) -> Path:
    root = PREPROCESSED_DIR.resolve()
    target = output_file.resolve()
    if root not in target.parents:
        raise ValueError(f"Refusing to write mask outside preprocessing output folder: {target}")
    relative = target.relative_to(root)
    if not relative.parts:
        raise ValueError(f"Could not identify preprocessing run for output: {target}")
    run_dir = root / relative.parts[0]
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Preprocessing run does not exist: {run_dir}")
    return run_dir


def threshold_name(threshold: float) -> str:
    return f"{threshold:.3f}".replace("-", "m").replace(".", "p")


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"
