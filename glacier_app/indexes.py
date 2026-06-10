from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from osgeo import gdal

try:
    from .config import PREPROCESSED_DIR
    from .result_exports import publish_index
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from glacier_app.config import PREPROCESSED_DIR
    from glacier_app.result_exports import publish_index


ProgressCallback = Callable[[str], None]

INDEX_NODATA = -9999.0


@dataclass(frozen=True)
class IndexSpec:
    name: str
    first_role: str
    second_role: str
    formula_label: str


@dataclass
class BandInput:
    label: str
    path: Path


@dataclass
class SceneInput:
    scene_id: str
    date: str
    sensor: str
    bands: dict[str, BandInput] = field(default_factory=dict)


@dataclass
class IndexResult:
    run_dir: Path
    scene_count: int
    index_count: int
    output_manifest: Path
    log_file: Path


INDEX_SPECS = [
    IndexSpec("NDSI", "green", "swir", "(Green - SWIR) / (Green + SWIR)"),
    IndexSpec("NDWI", "green", "nir", "(Green - NIR) / (Green + NIR)"),
]

BAND_ROLES = {
    "green": "green",
    "green b03": "green",
    "nir": "nir",
    "nir b08": "nir",
    "nir08": "nir",
    "swir": "swir",
    "swir b11": "swir",
    "swir16": "swir",
}


def calculate_run_indexes(run_dir: Path, progress: ProgressCallback | None = None) -> IndexResult:
    run_dir = checked_run_dir(run_dir)
    preprocessed_manifest = run_dir / "preprocessed_manifest.csv"
    if not preprocessed_manifest.exists():
        raise FileNotFoundError(f"Missing preprocessing manifest: {preprocessed_manifest}")

    scenes = read_preprocessed_scenes(preprocessed_manifest)
    output_root = run_dir / "indexes"
    output_root.mkdir(parents=True, exist_ok=True)
    output_manifest = run_dir / "index_manifest.csv"
    log_file = run_dir / "index_calculation.log"

    index_count = 0
    with output_manifest.open("w", newline="", encoding="utf-8") as manifest_handle, log_file.open(
        "w", encoding="utf-8"
    ) as log_handle:
        writer = csv.DictWriter(
            manifest_handle,
            fieldnames=[
                "scene_id",
                "date",
                "sensor",
                "index",
                "formula",
                "first_band",
                "second_band",
                "first_file",
                "second_file",
                "output_file",
                "status",
                "message",
            ],
        )
        writer.writeheader()

        for scene_index, scene in enumerate(scenes.values(), start=1):
            scene_dir = output_root / safe_name(scene.scene_id)
            scene_dir.mkdir(parents=True, exist_ok=True)
            for spec in INDEX_SPECS:
                first = scene.bands.get(spec.first_role)
                second = scene.bands.get(spec.second_role)
                output = scene_dir / f"{safe_name(scene.scene_id)}_{spec.name}.tif"
                if not first or not second:
                    missing = missing_roles(scene, spec)
                    writer.writerow(index_row(scene, spec, first, second, output, "missing", missing))
                    log_handle.write(f"{scene.scene_id} {spec.name}: missing {missing}\n")
                    continue

                emit(progress, f"Calculating {spec.name} for scene {scene_index}/{len(scenes)}: {scene.scene_id}")
                try:
                    compute_index_raster(first.path, second.path, output)
                    publish_index(output, spec.name, scene.date, scene.scene_id)
                    index_count += 1
                    writer.writerow(index_row(scene, spec, first, second, output, "ok", ""))
                    emit(progress, f"Created {output.name}")
                except Exception as exc:
                    message = str(exc)
                    writer.writerow(index_row(scene, spec, first, second, output, "failed", message))
                    log_handle.write(f"FAILED {scene.scene_id} {spec.name}: {message}\n")

    emit(progress, f"Index calculation complete: {index_count} rasters written.")
    return IndexResult(
        run_dir=run_dir,
        scene_count=len(scenes),
        index_count=index_count,
        output_manifest=output_manifest,
        log_file=log_file,
    )


def read_preprocessed_scenes(manifest_path: Path) -> dict[str, SceneInput]:
    scenes: dict[str, SceneInput] = {}
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "ok":
                continue
            role = band_role(row.get("band", ""))
            if not role:
                continue
            output_value = row.get("output_file", "")
            if not output_value:
                continue
            output_file = Path(output_value)
            if not output_file.exists():
                continue
            scene_id = row.get("scene_id", "")
            scene = scenes.setdefault(
                scene_id,
                SceneInput(
                    scene_id=scene_id,
                    date=row.get("date", ""),
                    sensor=row.get("sensor", ""),
                ),
            )
            scene.bands[role] = BandInput(label=row.get("band", ""), path=output_file)
    return scenes


def checked_run_dir(run_dir: Path) -> Path:
    root = PREPROCESSED_DIR.resolve()
    target = Path(run_dir).resolve()
    if root == target or root not in target.parents:
        raise ValueError(f"Refusing to write indexes outside preprocessing output folder: {target}")
    if not target.exists():
        raise FileNotFoundError(f"Preprocessing run does not exist: {target}")
    if not target.is_dir():
        raise ValueError(f"Preprocessing run is not a folder: {target}")
    return target


def compute_index_raster(first_file: Path, second_file: Path, output_file: Path) -> None:
    gdal.UseExceptions()
    ds_a = gdal.Open(str(first_file))
    ds_b = gdal.Open(str(second_file))
    if ds_a is None:
        raise RuntimeError(f"Could not open raster: {first_file}")
    if ds_b is None:
        raise RuntimeError(f"Could not open raster: {second_file}")

    band_a = ds_a.GetRasterBand(1)
    band_b = ds_b.GetRasterBand(1)
    a = band_a.ReadAsArray().astype(np.float32)
    b = band_b.ReadAsArray().astype(np.float32)

    nodata_a = band_a.GetNoDataValue()
    nodata_b = band_b.GetNoDataValue()
    invalid = np.zeros(a.shape, dtype=bool)
    if nodata_a is not None:
        invalid |= np.isclose(a, np.float32(nodata_a))
    if nodata_b is not None:
        invalid |= np.isclose(b, np.float32(nodata_b))
    denom = a + b
    invalid |= (denom == 0)
    safe_denom = np.where(invalid, np.float32(1.0), denom)
    result = np.where(invalid, INDEX_NODATA, (a - b) / safe_denom).astype(np.float32)

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(
        str(output_file),
        ds_a.RasterXSize,
        ds_a.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    if out_ds is None:
        raise RuntimeError(f"Could not create output raster: {output_file}")
    out_ds.SetGeoTransform(ds_a.GetGeoTransform())
    out_ds.SetProjection(ds_a.GetProjection())
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(INDEX_NODATA)
    out_band.WriteArray(result)
    out_ds.FlushCache()
    out_ds = None
    ds_a = None
    ds_b = None


def band_role(label: str) -> str:
    return BAND_ROLES.get(label.strip().lower(), "")


def missing_roles(scene: SceneInput, spec: IndexSpec) -> str:
    missing = []
    if spec.first_role not in scene.bands:
        missing.append(spec.first_role)
    if spec.second_role not in scene.bands:
        missing.append(spec.second_role)
    return ", ".join(missing)


def index_row(
    scene: SceneInput,
    spec: IndexSpec,
    first: BandInput | None,
    second: BandInput | None,
    output: Path,
    status: str,
    message: str,
) -> dict[str, str]:
    return {
        "scene_id": scene.scene_id,
        "date": scene.date,
        "sensor": scene.sensor,
        "index": spec.name,
        "formula": spec.formula_label,
        "first_band": first.label if first else "",
        "second_band": second.label if second else "",
        "first_file": str(first.path) if first else "",
        "second_file": str(second.path) if second else "",
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
