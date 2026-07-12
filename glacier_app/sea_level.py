from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
from osgeo import gdal

from .config import AOI_CONFIG, APP_DIR


SEA_LEVEL_DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
SEA_LEVEL_VARIABLE = "zos"
SEA_LEVEL_START_DATE = "2017-01-01"
SEA_LEVEL_END_DATE = "2026-05-26"
SEA_LEVEL_OUTPUT_DIR = APP_DIR / "outputs" / "sea_level"
SEA_LEVEL_FIGURE_DIR = SEA_LEVEL_OUTPUT_DIR / "figures"


@dataclass
class SeaLevelRecord:
    when: date | None
    mean_m: float
    min_m: float
    max_m: float


@dataclass
class SeaLevelImportResult:
    data_file: Path
    figure_file: Path
    record_count: int
    first_date: str
    last_date: str
    mean_m: float
    min_m: float
    max_m: float
    trend_mm_per_year: float | None
    downloaded: bool


ProgressCallback = Callable[[str], None] | None


def import_copernicus_sea_level(
    data_file: Path | None = None,
    force_download: bool = False,
    progress: ProgressCallback = None,
) -> SeaLevelImportResult:
    data_file = Path(data_file) if data_file is not None else default_sea_level_data_file()
    downloaded = False
    if data_file.exists():
        if progress is not None:
            progress(f"Using selected sea-level NetCDF file: {data_file.name}")
    elif data_file == default_sea_level_data_file() and force_download:
        download_copernicus_sea_level(data_file, progress=progress)
        downloaded = True
    elif data_file == default_sea_level_data_file():
        download_copernicus_sea_level(data_file, progress=progress)
        downloaded = True
    else:
        raise FileNotFoundError(f"Selected sea-level NetCDF file does not exist: {data_file}")

    if progress is not None:
        progress("Reading sea-level NetCDF and building figure...")
    records = read_sea_level_series(data_file)
    figure_file = default_sea_level_figure_file(data_file)
    render_sea_level_figure(records, figure_file)
    return summarize_import(data_file, figure_file, records, downloaded)


def download_copernicus_sea_level(output_file: Path, progress: ProgressCallback = None) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not copernicusmarine_available():
        raise RuntimeError(
            "Copernicus Marine toolbox is not installed. Run "
            "`conda env update -f environment.yml` and activate the glacier-monitoring environment."
        )
    if progress is not None and not copernicus_credentials_configured():
        progress("No .env Copernicus credentials found; trying saved Copernicus Marine login.")

    bbox = load_project_bbox()
    command = copernicus_subset_command(output_file, bbox)
    if progress is not None:
        progress("Downloading Copernicus sea-level data for the project AOI...")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        if len(details) > 1200:
            details = details[-1200:]
        raise RuntimeError(f"Copernicus sea-level download failed.\n{details}")
    if not output_file.exists():
        raise RuntimeError(f"Copernicus download finished but the NetCDF file was not created: {output_file}")


def copernicus_subset_command(output_file: Path, bbox: dict[str, float]) -> list[str]:
    executable = shutil.which("copernicusmarine")
    command = [executable] if executable else [sys.executable, "-m", "copernicusmarine"]
    command.extend(
        [
            "subset",
            "--dataset-id",
            SEA_LEVEL_DATASET_ID,
            "--variable",
            SEA_LEVEL_VARIABLE,
            "--minimum-longitude",
            str(bbox["west"]),
            "--maximum-longitude",
            str(bbox["east"]),
            "--minimum-latitude",
            str(bbox["south"]),
            "--maximum-latitude",
            str(bbox["north"]),
            "--start-datetime",
            f"{SEA_LEVEL_START_DATE}T00:00:00",
            "--end-datetime",
            f"{SEA_LEVEL_END_DATE}T23:59:59",
            "--output-directory",
            str(output_file.parent),
            "--output-filename",
            output_file.name,
            "--force-download",
        ]
    )
    return command


def copernicusmarine_available() -> bool:
    if shutil.which("copernicusmarine"):
        return True
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "copernicusmarine", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def copernicus_credentials_configured() -> bool:
    username = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") or os.environ.get("COPERNICUSMARINE_USERNAME")
    password = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD") or os.environ.get("COPERNICUSMARINE_PASSWORD")
    return bool(username and password)


def load_project_bbox() -> dict[str, float]:
    with AOI_CONFIG.open(encoding="utf-8") as handle:
        config = json.load(handle)
    bbox = config.get("bbox", config)
    return {
        "west": float(bbox["west"]),
        "south": float(bbox["south"]),
        "east": float(bbox["east"]),
        "north": float(bbox["north"]),
    }


def default_sea_level_data_file() -> Path:
    start = SEA_LEVEL_START_DATE.replace("-", "")
    end = SEA_LEVEL_END_DATE.replace("-", "")
    return SEA_LEVEL_OUTPUT_DIR / f"vatnajokull_28wds_sea_level_{SEA_LEVEL_VARIABLE}_{start}_{end}.nc"


def default_sea_level_figure_file(data_file: Path) -> Path:
    SEA_LEVEL_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    return SEA_LEVEL_FIGURE_DIR / f"{data_file.stem}_figure.png"


def read_sea_level_series(data_file: Path) -> list[SeaLevelRecord]:
    xarray_error: Exception | None = None
    try:
        return read_sea_level_series_xarray(data_file)
    except Exception as exc:
        xarray_error = exc

    try:
        return read_sea_level_series_gdal(data_file)
    except Exception as gdal_error:
        raise RuntimeError(
            "Could not read the Copernicus NetCDF file. Install/update the project "
            "environment so xarray and netCDF4 are available:\n"
            "  conda env update -f environment.yml\n\n"
            f"xarray reader error: {xarray_error}\n"
            f"GDAL reader error: {gdal_error}"
        ) from gdal_error


def read_sea_level_series_xarray(data_file: Path) -> list[SeaLevelRecord]:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is not installed.") from exc

    with xr.open_dataset(data_file, decode_times=True, mask_and_scale=True) as dataset:
        if SEA_LEVEL_VARIABLE in dataset.data_vars:
            data_array = dataset[SEA_LEVEL_VARIABLE]
        elif len(dataset.data_vars) == 1:
            data_array = dataset[next(iter(dataset.data_vars))]
        else:
            available = ", ".join(dataset.data_vars)
            raise RuntimeError(f"Variable `{SEA_LEVEL_VARIABLE}` was not found. Available variables: {available}")

        time_dim = xarray_time_dimension(data_array)
        if time_dim is None:
            values = np.asarray(data_array.values, dtype=np.float64)
            record = sea_level_record_from_values(values, None)
            return [record] if record is not None else []

        data_array = data_array.transpose(time_dim, ...)
        times = np.asarray(data_array.coords[time_dim].values)
        values = np.asarray(data_array.values, dtype=np.float64)

    records = []
    for index in range(values.shape[0]):
        when = xarray_date_from_value(times[index]) if index < len(times) else None
        record = sea_level_record_from_values(values[index], when)
        if record is not None:
            records.append(record)
    if not records:
        raise RuntimeError(f"No valid sea-level values were found in {data_file}")
    return records


def xarray_time_dimension(data_array) -> str | None:
    for dim in data_array.dims:
        if str(dim).lower() in {"time", "time_counter", "valid_time"}:
            return str(dim)
    for dim in data_array.dims:
        coord = data_array.coords.get(dim)
        if coord is None:
            continue
        try:
            if np.issubdtype(coord.dtype, np.datetime64):
                return str(dim)
        except TypeError:
            pass
    return None


def xarray_date_from_value(value) -> date | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        text = np.datetime_as_string(value, unit="D")
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if all(hasattr(value, attribute) for attribute in ("year", "month", "day")):
        try:
            return date(int(value.year), int(value.month), int(value.day))
        except ValueError:
            return None
    return None


def sea_level_record_from_values(values, when: date | None) -> SeaLevelRecord | None:
    array = np.asarray(values, dtype=np.float64)
    valid = np.isfinite(array) & (np.abs(array) < 1.0e10)
    if not valid.any():
        return None
    finite_values = array[valid]
    return SeaLevelRecord(
        when=when,
        mean_m=float(np.mean(finite_values)),
        min_m=float(np.min(finite_values)),
        max_m=float(np.max(finite_values)),
    )


def read_sea_level_series_gdal(data_file: Path) -> list[SeaLevelRecord]:
    gdal.UseExceptions()
    dataset = open_sea_level_dataset(data_file)
    metadata = dataset.GetMetadata()
    fallback_start = date_from_filename(data_file) or date.fromisoformat(SEA_LEVEL_START_DATE)
    records: list[SeaLevelRecord] = []
    for band_index in range(1, dataset.RasterCount + 1):
        band = dataset.GetRasterBand(band_index)
        array = band.ReadAsArray().astype(np.float32)
        nodata = band.GetNoDataValue()
        valid = np.isfinite(array) & (np.abs(array) < 1.0e10)
        if nodata is not None:
            valid &= ~np.isclose(array, np.float32(nodata))
        if not valid.any():
            continue
        values = array[valid]
        records.append(
            SeaLevelRecord(
                when=band_date(band, metadata, fallback_start, band_index),
                mean_m=float(np.mean(values)),
                min_m=float(np.min(values)),
                max_m=float(np.max(values)),
            )
        )
    dataset = None
    if not records:
        raise RuntimeError(f"No valid sea-level values were found in {data_file}")
    return records


def open_sea_level_dataset(data_file: Path) -> gdal.Dataset:
    direct_name = f'NETCDF:"{data_file}":{SEA_LEVEL_VARIABLE}'
    dataset = gdal.Open(direct_name)
    if dataset is not None and dataset.RasterCount > 0:
        return dataset

    root = gdal.Open(str(data_file))
    if root is None:
        raise RuntimeError(f"Could not open sea-level NetCDF file: {data_file}")
    for name, description in root.GetSubDatasets():
        text = f"{name} {description}".lower()
        if f":{SEA_LEVEL_VARIABLE.lower()}" in text or f"[{SEA_LEVEL_VARIABLE.lower()}]" in text:
            dataset = gdal.Open(name)
            if dataset is not None and dataset.RasterCount > 0:
                root = None
                return dataset
    if root.RasterCount > 0:
        return root
    raise RuntimeError(f"Could not find variable `{SEA_LEVEL_VARIABLE}` in {data_file}")


def band_date(
    band: gdal.Band,
    dataset_metadata: dict[str, str],
    fallback_start: date,
    band_index: int,
) -> date | None:
    metadata = band.GetMetadata()
    raw_value = first_metadata_value(metadata, "NETCDF_DIM_time", "NETCDF_DIM_time_VALUES", "time")
    units = first_metadata_value(
        dataset_metadata,
        "time#units",
        "NETCDF_DIM_time_UNITS",
        "time_units",
    )
    if raw_value and units:
        parsed = parse_cf_time(raw_value, units)
        if parsed is not None:
            return parsed
    return fallback_start + timedelta(days=band_index - 1)


def first_metadata_value(metadata: dict[str, str], *keys: str) -> str:
    lower = {key.lower(): value for key, value in metadata.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value:
            return str(value)
    return ""


def parse_cf_time(raw_value: str, units: str) -> date | None:
    try:
        value = float(str(raw_value).split()[0])
    except (TypeError, ValueError):
        return None
    match = re.search(r"^\s*(\w+)\s+since\s+(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2}))?", units)
    if not match:
        return None
    unit = match.group(1).lower()
    origin_text = match.group(2)
    time_text = match.group(3) or "00:00:00"
    try:
        origin = datetime.fromisoformat(f"{origin_text}T{time_text}")
    except ValueError:
        return None
    if unit.startswith("day"):
        delta = timedelta(days=value)
    elif unit.startswith("hour"):
        delta = timedelta(hours=value)
    elif unit.startswith("sec"):
        delta = timedelta(seconds=value)
    elif unit.startswith("minute"):
        delta = timedelta(minutes=value)
    else:
        return None
    return (origin + delta).date()


def date_from_filename(path: Path) -> date | None:
    match = re.search(r"_(\d{8})_\d{8}(?:\.|_)", path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def summarize_import(
    data_file: Path,
    figure_file: Path,
    records: list[SeaLevelRecord],
    downloaded: bool,
) -> SeaLevelImportResult:
    means = np.array([record.mean_m for record in records], dtype=np.float64)
    first_date = records[0].when.isoformat() if records[0].when else "record 1"
    last_date = records[-1].when.isoformat() if records[-1].when else f"record {len(records)}"
    return SeaLevelImportResult(
        data_file=data_file,
        figure_file=figure_file,
        record_count=len(records),
        first_date=first_date,
        last_date=last_date,
        mean_m=float(np.mean(means)),
        min_m=float(np.min([record.min_m for record in records])),
        max_m=float(np.max([record.max_m for record in records])),
        trend_mm_per_year=trend_mm_per_year(records),
        downloaded=downloaded,
    )


def trend_mm_per_year(records: list[SeaLevelRecord]) -> float | None:
    dated = [record for record in records if record.when is not None and np.isfinite(record.mean_m)]
    if len(dated) < 2:
        return None
    start = dated[0].when
    x = np.array([(record.when - start).days / 365.25 for record in dated], dtype=np.float64)
    y = np.array([record.mean_m for record in dated], dtype=np.float64)
    if np.max(x) <= 0:
        return None
    slope, _intercept = np.polyfit(x, y, 1)
    return float(slope * 1000.0)


def render_sea_level_figure(records: list[SeaLevelRecord], output_file: Path) -> None:
    monthly = monthly_records(records)
    plot_records = monthly if len(monthly) >= 2 else records
    values = np.array([record.mean_m for record in plot_records], dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        raise RuntimeError("Sea-level figure could not be rendered because all values are invalid.")

    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:
        render_sea_level_figure_fallback(records, output_file)
        return

    output_file.parent.mkdir(parents=True, exist_ok=True)
    means = np.array([record.mean_m for record in plot_records], dtype=np.float64)
    mins = np.array([record.min_m for record in plot_records], dtype=np.float64)
    maxs = np.array([record.max_m for record in plot_records], dtype=np.float64)
    dated = all(record.when is not None for record in plot_records)
    x_values = [record.when for record in plot_records] if dated else np.arange(len(plot_records))

    fig, ax = plt.subplots(figsize=(12.5, 7.2), dpi=180)
    fig.patch.set_facecolor("#f4f8f9")
    ax.set_facecolor("#ffffff")

    if np.isfinite(mins).any() and np.isfinite(maxs).any():
        ax.fill_between(
            x_values,
            mins,
            maxs,
            color="#9ed2eb",
            alpha=0.28,
            linewidth=0,
            label="AOI min-max range",
        )
    ax.plot(
        x_values,
        means,
        color="#0077b6",
        linewidth=2.4,
        marker="o",
        markersize=3.2,
        markerfacecolor="#005b91",
        markeredgewidth=0,
        label="AOI mean sea level",
    )

    trend = trend_mm_per_year(records)
    if trend is not None:
        trend_records = [record for record in plot_records if record.when is not None and np.isfinite(record.mean_m)]
        if len(trend_records) >= 2:
            start = trend_records[0].when
            trend_x = np.array([(record.when - start).days / 365.25 for record in trend_records], dtype=np.float64)
            trend_y = np.array([record.mean_m for record in trend_records], dtype=np.float64)
            slope, intercept = np.polyfit(trend_x, trend_y, 1)
            ax.plot(
                [record.when for record in trend_records],
                intercept + slope * trend_x,
                color="#d1495b",
                linewidth=2.0,
                linestyle="--",
                label=f"Trend {trend:.1f} mm/yr",
            )

    title = "Mean sea surface height above geoid"
    subtitle = "For the project AOI"
    ax.set_title(title, loc="left", fontsize=18, fontweight="bold", color="#141d22", pad=18)
    ax.text(
        0.0,
        1.015,
        subtitle,
        transform=ax.transAxes,
        fontsize=10.5,
        color="#53656e",
        va="bottom",
    )
    ax.set_ylabel("Sea level (m)", color="#263238")
    ax.grid(True, axis="y", color="#d6e1e6", linewidth=0.8)
    ax.grid(True, axis="x", color="#edf3f5", linewidth=0.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#708892")
    ax.spines["bottom"].set_color("#708892")
    ax.tick_params(colors="#445761")

    if dated:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_minor_locator(mdates.MonthLocator(interval=6))
        fig.autofmt_xdate(rotation=0, ha="center")
    else:
        ax.set_xlabel("Record")

    raw_means = np.array([record.mean_m for record in records], dtype=np.float64)
    min_value = float(np.nanmin([record.min_m for record in records]))
    max_value = float(np.nanmax([record.max_m for record in records]))
    trend_text = f"{trend:.1f} mm/yr" if trend is not None else "n/a"
    summary = (
        f"Records: {len(records):,}\n"
        f"Mean: {np.nanmean(raw_means):.3f} m\n"
        f"Min: {min_value:.3f} m\n"
        f"Max: {max_value:.3f} m\n"
        f"Trend: {trend_text}"
    )
    ax.text(
        0.985,
        0.965,
        summary,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=10,
        color="#141d22",
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "#eef6f9",
            "edgecolor": "#b8cad2",
            "linewidth": 0.9,
        },
    )
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    fig.text(
        0.015,
        0.018,
        "Source: Copernicus Marine Global Ocean Physics Reanalysis",
        fontsize=8.5,
        color="#53656e",
    )
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 0.98))
    fig.savefig(output_file, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_sea_level_figure_fallback(records: list[SeaLevelRecord], output_file: Path) -> None:
    monthly = monthly_records(records)
    plot_records = monthly if len(monthly) >= 2 else records
    values = np.array([record.mean_m for record in plot_records], dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        raise RuntimeError("Sea-level figure could not be rendered because all values are invalid.")

    scale = 2
    width, height = 1100 * scale, 620 * scale
    left, right, top, bottom = 96 * scale, 52 * scale, 98 * scale, 88 * scale
    plot_x0, plot_y0 = left, top
    plot_x1, plot_y1 = width - right, height - bottom
    rgb = np.empty((3, height, width), dtype=np.uint8)
    rgb[:] = np.array([244, 248, 249], dtype=np.uint8)[:, None, None]
    fill_rect(rgb, plot_x0, plot_y0, plot_x1, plot_y1, (255, 255, 255))

    value_min = float(np.nanmin(values))
    value_max = float(np.nanmax(values))
    span = value_max - value_min
    if span <= 0:
        span = 0.1
    y_min = value_min - span * 0.12
    y_max = value_max + span * 0.12

    draw_text(rgb, "SEA LEVEL ZOS", 34 * scale, 24 * scale, (20, 29, 33), 3 * scale)
    draw_text(
        rgb,
        "MEAN SEA SURFACE HEIGHT ABOVE GEOID M",
        36 * scale,
        62 * scale,
        (83, 101, 110),
        2 * scale,
    )
    draw_text(
        rgb,
        "SOURCE COPERNICUS MARINE GLOBAL OCEAN PHYSICS REANALYSIS",
        36 * scale,
        590 * scale,
        (83, 101, 110),
        scale,
    )

    grid_color = (214, 225, 230)
    axis_color = (42, 54, 60)
    for tick in range(6):
        y = int(round(plot_y1 - tick * (plot_y1 - plot_y0) / 5))
        draw_line(rgb, plot_x0, y, plot_x1, y, grid_color, scale)
        value = y_min + tick * (y_max - y_min) / 5
        draw_text(rgb, f"{value:.2f}", 24 * scale, y - 7 * scale, (72, 86, 94), scale)
    draw_line(rgb, plot_x0, plot_y0, plot_x0, plot_y1, axis_color, 2 * scale)
    draw_line(rgb, plot_x0, plot_y1, plot_x1, plot_y1, axis_color, 2 * scale)

    x_values = record_x_values(plot_records)
    x_min = float(np.min(x_values))
    x_max = float(np.max(x_values))
    if x_max <= x_min:
        x_max = x_min + 1.0
    points: list[tuple[int, int]] = []
    for x_value, value in zip(x_values, values):
        x = int(round(plot_x0 + (x_value - x_min) / (x_max - x_min) * (plot_x1 - plot_x0)))
        y = int(round(plot_y1 - (value - y_min) / (y_max - y_min) * (plot_y1 - plot_y0)))
        points.append((x, y))
    for start, end in zip(points, points[1:]):
        draw_line(rgb, start[0], start[1], end[0], end[1], (0, 119, 182), 3 * scale)
    for x, y in points[:: max(1, len(points) // 80)]:
        fill_rect(rgb, x - 2 * scale, y - 2 * scale, x + 3 * scale, y + 3 * scale, (0, 87, 142))

    draw_x_labels(rgb, plot_records, plot_x0, plot_x1, plot_y1, scale)
    draw_summary(rgb, records, width - 352 * scale, 24 * scale, scale)
    write_rgb_png(output_file, rgb)


def monthly_records(records: list[SeaLevelRecord]) -> list[SeaLevelRecord]:
    buckets: dict[tuple[int, int], list[SeaLevelRecord]] = {}
    for record in records:
        if record.when is None:
            return []
        buckets.setdefault((record.when.year, record.when.month), []).append(record)
    monthly: list[SeaLevelRecord] = []
    for year, month in sorted(buckets):
        items = buckets[(year, month)]
        means = np.array([item.mean_m for item in items], dtype=np.float64)
        mins = np.array([item.min_m for item in items], dtype=np.float64)
        maxs = np.array([item.max_m for item in items], dtype=np.float64)
        monthly.append(
            SeaLevelRecord(
                when=date(year, month, 15),
                mean_m=float(np.nanmean(means)),
                min_m=float(np.nanmin(mins)),
                max_m=float(np.nanmax(maxs)),
            )
        )
    return monthly


def record_x_values(records: list[SeaLevelRecord]) -> np.ndarray:
    if records and records[0].when is not None:
        start = records[0].when
        return np.array([(record.when - start).days for record in records], dtype=np.float64)
    return np.arange(len(records), dtype=np.float64)


def draw_x_labels(
    rgb,
    records: list[SeaLevelRecord],
    plot_x0: int,
    plot_x1: int,
    plot_y1: int,
    scale: int = 1,
) -> None:
    if not records:
        return
    if records[0].when is None or records[-1].when is None:
        draw_text(rgb, "START", plot_x0, plot_y1 + 18 * scale, (72, 86, 94), scale)
        draw_text(rgb, "END", plot_x1 - 22 * scale, plot_y1 + 18 * scale, (72, 86, 94), scale)
        return
    start_year = records[0].when.year
    end_year = records[-1].when.year
    years = list(range(start_year, end_year + 1))
    start = date(start_year, 1, 1)
    end = date(end_year + 1, 1, 1)
    total_days = max(1, (end - start).days)
    for year in years:
        x = int(round(plot_x0 + (date(year, 1, 1) - start).days / total_days * (plot_x1 - plot_x0)))
        draw_line(rgb, x, plot_y1, x, plot_y1 + 6 * scale, (42, 54, 60), scale)
        if year == start_year or year == end_year or year % 2 == 0:
            draw_text(rgb, str(year), x - 14 * scale, plot_y1 + 18 * scale, (72, 86, 94), scale)


def draw_summary(rgb, records: list[SeaLevelRecord], x: int, y: int, scale: int = 1) -> None:
    means = np.array([record.mean_m for record in records], dtype=np.float64)
    min_value = float(np.min([record.min_m for record in records]))
    max_value = float(np.max([record.max_m for record in records]))
    trend = trend_mm_per_year(records)
    fill_rect(rgb, x, y, x + 316 * scale, y + 138 * scale, (235, 244, 247))
    draw_rect(rgb, x, y, x + 316 * scale, y + 138 * scale, (184, 202, 210), scale)
    draw_text(rgb, "AOI SUMMARY", x + 14 * scale, y + 13 * scale, (20, 29, 33), 2 * scale)
    draw_text(rgb, f"MEAN {np.mean(means):.3f} M", x + 14 * scale, y + 42 * scale, (20, 29, 33), scale)
    draw_text(rgb, f"MIN  {min_value:.3f} M", x + 14 * scale, y + 62 * scale, (20, 29, 33), scale)
    draw_text(rgb, f"MAX  {max_value:.3f} M", x + 14 * scale, y + 82 * scale, (20, 29, 33), scale)
    if trend is not None:
        draw_text(rgb, f"TREND {trend:.1f} MM/YR", x + 14 * scale, y + 102 * scale, (20, 29, 33), scale)


def fill_rect(rgb, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    x0 = max(0, min(rgb.shape[2], x0))
    x1 = max(0, min(rgb.shape[2], x1))
    y0 = max(0, min(rgb.shape[1], y0))
    y1 = max(0, min(rgb.shape[1], y1))
    if x1 <= x0 or y1 <= y0:
        return
    rgb[:, y0:y1, x0:x1] = np.array(color, dtype=np.uint8)[:, None, None]


def draw_rect(rgb, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], width: int = 1) -> None:
    for offset in range(width):
        draw_line(rgb, x0, y0 + offset, x1, y0 + offset, color, 1)
        draw_line(rgb, x0, y1 - offset, x1, y1 - offset, color, 1)
        draw_line(rgb, x0 + offset, y0, x0 + offset, y1, color, 1)
        draw_line(rgb, x1 - offset, y0, x1 - offset, y1, color, 1)


def draw_line(rgb, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], width: int = 1) -> None:
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    xs = np.linspace(x0, x1, steps + 1)
    ys = np.linspace(y0, y1, steps + 1)
    radius = max(0, width // 2)
    for x_float, y_float in zip(xs, ys):
        x = int(round(x_float))
        y = int(round(y_float))
        fill_rect(rgb, x - radius, y - radius, x + radius + 1, y + radius + 1, color)


def write_rgb_png(output_file: Path, rgb) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    mem_driver = gdal.GetDriverByName("MEM")
    dataset = mem_driver.Create("", rgb.shape[2], rgb.shape[1], 3, gdal.GDT_Byte)
    if dataset is None:
        raise RuntimeError("Could not create in-memory sea-level figure.")
    for index in range(3):
        dataset.GetRasterBand(index + 1).WriteArray(rgb[index])
    png_driver = gdal.GetDriverByName("PNG")
    png = png_driver.CreateCopy(str(output_file), dataset)
    if png is None:
        raise RuntimeError(f"Could not write sea-level figure: {output_file}")
    png.FlushCache()
    png = None
    dataset = None


def draw_text(rgb, text: str, x: int, y: int, color: tuple[int, int, int], scale: int = 1) -> None:
    cursor = x
    color_array = np.array(color, dtype=np.uint8)[:, None, None]
    for char in text.upper():
        glyph = FONT.get(char, FONT[" "])
        for row_index, row in enumerate(glyph):
            for col_index, value in enumerate(row):
                if value != "1":
                    continue
                x0 = cursor + col_index * scale
                y0 = y + row_index * scale
                if 0 <= x0 < rgb.shape[2] and 0 <= y0 < rgb.shape[1]:
                    rgb[:, y0 : y0 + scale, x0 : x0 + scale] = color_array
        cursor += (len(glyph[0]) + 1) * scale


FONT = {
    " ": ("000", "000", "000", "000", "000", "000", "000"),
    "-": ("000", "000", "000", "111", "000", "000", "000"),
    ".": ("0", "0", "0", "0", "0", "0", "1"),
    "/": ("0001", "0001", "0010", "0010", "0100", "0100", "1000"),
    ":": ("0", "1", "0", "0", "1", "0", "0"),
    "0": ("111", "101", "101", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "010", "010", "111"),
    "2": ("111", "001", "001", "111", "100", "100", "111"),
    "3": ("111", "001", "001", "111", "001", "001", "111"),
    "4": ("101", "101", "101", "111", "001", "001", "001"),
    "5": ("111", "100", "100", "111", "001", "001", "111"),
    "6": ("111", "100", "100", "111", "101", "101", "111"),
    "7": ("111", "001", "001", "010", "010", "100", "100"),
    "8": ("111", "101", "101", "111", "101", "101", "111"),
    "9": ("111", "101", "101", "111", "001", "001", "111"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("111", "010", "010", "010", "010", "010", "111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}
