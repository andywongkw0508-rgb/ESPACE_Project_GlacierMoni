from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
from osgeo import gdal

from .config import PREPROCESSED_DIR, RESULTS_DIR
from .results import ProcessingOutput


@dataclass
class BoundaryCandidate:
    output: ProcessingOutput
    mask_file: Path
    when: date


@dataclass
class MaskArea:
    file: Path
    pixels: int
    pixel_area_m2: float
    area_m2: float
    area_km2: float


@dataclass
class GlacierRetreatResult:
    older: ProcessingOutput
    newer: ProcessingOutput
    older_mask: MaskArea
    newer_mask: MaskArea
    area_change_km2: float
    area_reduced_km2: float
    percent_reduced: float | None
    report_file: Path

    @property
    def is_retreat(self) -> bool:
        return self.area_change_km2 < 0

    def summary_text(self) -> str:
        percent_text = f"{self.percent_reduced:.2f}%" if self.percent_reduced is not None else "n/a"
        change_label = "Area reduced" if self.is_retreat else "Area increased"
        change_value = abs(self.area_change_km2)
        return (
            "Glacier retreat comparison\n"
            f"Older boundary: {self.older.date} | {self.older.scene_id}\n"
            f"Latest boundary: {self.newer.date} | {self.newer.scene_id}\n"
            f"Older glacier area: {self.older_mask.area_km2:.3f} km2\n"
            f"Latest glacier area: {self.newer_mask.area_km2:.3f} km2\n"
            f"{change_label}: {change_value:.3f} km2\n"
            f"Percent reduced: {percent_text}\n"
            f"Older mask: {self.older_mask.file}\n"
            f"Latest mask: {self.newer_mask.file}\n"
            f"Report: {self.report_file}"
        )


def compare_glacier_retreat(
    boundaries: Iterable[ProcessingOutput],
    preferred_boundary: ProcessingOutput | None = None,
) -> GlacierRetreatResult:
    candidates = boundary_candidates(boundaries)
    if len(candidates) < 2:
        raise ValueError(
            "Load at least two boundary results with source glacier masks before comparing glacier retreat."
        )

    preferred = preferred_candidates(candidates, preferred_boundary)
    if len(preferred) >= 2:
        candidates = preferred
    else:
        ndsi_candidates = [
            candidate for candidate in candidates
            if "NDSI" in f"{candidate.output.label} {candidate.output.formula} {candidate.mask_file.name}".upper()
        ]
        if len(ndsi_candidates) >= 2:
            candidates = ndsi_candidates

    candidates.sort(key=lambda item: (item.when, item.output.run_name, item.output.scene_id, str(item.mask_file)))
    older = candidates[0]
    newer = candidates[-1]
    if older.when == newer.when and older.output.output_file == newer.output.output_file:
        raise ValueError("The oldest and latest boundary candidates are the same result.")

    older_area = measure_mask_area(older.mask_file)
    newer_area = measure_mask_area(newer.mask_file)
    area_change_km2 = newer_area.area_km2 - older_area.area_km2
    area_reduced_km2 = max(0.0, older_area.area_km2 - newer_area.area_km2)
    percent_reduced = (
        area_reduced_km2 / older_area.area_km2 * 100.0
        if older_area.area_km2 > 0
        else None
    )
    result = GlacierRetreatResult(
        older=older.output,
        newer=newer.output,
        older_mask=older_area,
        newer_mask=newer_area,
        area_change_km2=area_change_km2,
        area_reduced_km2=area_reduced_km2,
        percent_reduced=percent_reduced,
        report_file=Path(),
    )
    result.report_file = write_retreat_report(result)
    return result


def boundary_candidates(boundaries: Iterable[ProcessingOutput]) -> list[BoundaryCandidate]:
    candidates = []
    for output in boundaries:
        if output.kind != "Boundary":
            continue
        when = parse_output_date(output.date)
        if when is None:
            continue
        mask_file = boundary_source_mask(output)
        if mask_file is None:
            continue
        candidates.append(BoundaryCandidate(output=output, mask_file=mask_file, when=when))
    return candidates


def preferred_candidates(
    candidates: list[BoundaryCandidate],
    preferred_boundary: ProcessingOutput | None,
) -> list[BoundaryCandidate]:
    if preferred_boundary is None or preferred_boundary.kind != "Boundary":
        return []
    same_label = [
        candidate for candidate in candidates
        if candidate.output.label == preferred_boundary.label
    ]
    if len(same_label) >= 2:
        return same_label
    preferred_text = f"{preferred_boundary.label} {preferred_boundary.formula}".upper()
    if "NDSI" in preferred_text:
        return [
            candidate for candidate in candidates
            if "NDSI" in f"{candidate.output.label} {candidate.output.formula} {candidate.mask_file.name}".upper()
        ]
    return []


def parse_output_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def boundary_source_mask(output: ProcessingOutput) -> Path | None:
    if output.source_file is not None and output.source_file.exists():
        return output.source_file
    manifest = boundary_manifest_for_output(output.output_file)
    if manifest is None:
        return None
    try:
        output_resolved = output.output_file.resolve()
    except OSError:
        return None
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            source_value = row.get("source_file", "")
            output_value = row.get("output_file", "")
            if not source_value or not output_value:
                continue
            try:
                row_output = Path(output_value).resolve()
            except OSError:
                continue
            if row_output != output_resolved:
                continue
            source = Path(source_value)
            if source.exists():
                return source
    return None


def boundary_manifest_for_output(output_file: Path) -> Path | None:
    root = PREPROCESSED_DIR.resolve()
    try:
        target = output_file.resolve()
    except OSError:
        return None
    if root not in target.parents:
        return None
    relative = target.relative_to(root)
    if not relative.parts:
        return None
    manifest = root / relative.parts[0] / "boundary_manifest.csv"
    return manifest if manifest.exists() else None


def measure_mask_area(mask_file: Path) -> MaskArea:
    gdal.UseExceptions()
    dataset = gdal.Open(str(mask_file))
    if dataset is None:
        raise RuntimeError(f"Could not open glacier mask: {mask_file}")
    band = dataset.GetRasterBand(1)
    array = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= ~np.isclose(array, np.float32(nodata))
    glacier = valid & (array > 0)
    pixel_count = int(np.count_nonzero(glacier))
    gt = dataset.GetGeoTransform()
    pixel_area_m2 = abs(float(gt[1]) * float(gt[5]) - float(gt[2]) * float(gt[4]))
    dataset = None
    area_m2 = pixel_count * pixel_area_m2
    return MaskArea(
        file=mask_file,
        pixels=pixel_count,
        pixel_area_m2=pixel_area_m2,
        area_m2=area_m2,
        area_km2=area_m2 / 1_000_000.0,
    )


def write_retreat_report(result: GlacierRetreatResult) -> Path:
    output_dir = RESULTS_DIR / "glacier_retreat"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / (
        f"glacier_retreat_{safe_name(result.older.date)}_to_{safe_name(result.newer.date)}_{timestamp}.csv"
    )
    fields = [
        "created_at",
        "older_date",
        "latest_date",
        "older_scene_id",
        "latest_scene_id",
        "older_boundary_file",
        "latest_boundary_file",
        "older_mask_file",
        "latest_mask_file",
        "older_area_km2",
        "latest_area_km2",
        "area_change_km2",
        "area_reduced_km2",
        "percent_reduced",
        "older_pixels",
        "latest_pixels",
        "pixel_area_m2",
    ]
    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "older_date": result.older.date,
                "latest_date": result.newer.date,
                "older_scene_id": result.older.scene_id,
                "latest_scene_id": result.newer.scene_id,
                "older_boundary_file": str(result.older.output_file),
                "latest_boundary_file": str(result.newer.output_file),
                "older_mask_file": str(result.older_mask.file),
                "latest_mask_file": str(result.newer_mask.file),
                "older_area_km2": f"{result.older_mask.area_km2:.6f}",
                "latest_area_km2": f"{result.newer_mask.area_km2:.6f}",
                "area_change_km2": f"{result.area_change_km2:.6f}",
                "area_reduced_km2": f"{result.area_reduced_km2:.6f}",
                "percent_reduced": "" if result.percent_reduced is None else f"{result.percent_reduced:.6f}",
                "older_pixels": str(result.older_mask.pixels),
                "latest_pixels": str(result.newer_mask.pixels),
                "pixel_area_m2": f"{result.older_mask.pixel_area_m2:.6f}",
            }
        )
    return output_file


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"
