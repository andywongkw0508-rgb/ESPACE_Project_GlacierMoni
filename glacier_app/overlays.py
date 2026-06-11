from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from osgeo import gdal

from .bands import check_scene_bands
from .config import OVERLAY_BASE_SCENE_ID
from .result_exports import overlay_dir, safe_name
from .results import ProcessingOutput


# Cool (oldest/largest) → warm (newest/smallest) to show glacier retreat direction.
# Designed for up to 10 years; additional years cycle back from the start.
YEAR_COLORS = [
    (63,  84, 186),   # deep blue   — oldest
    (32, 119, 180),   # blue
    (31, 160, 187),   # teal
    (44, 177, 133),   # green-teal
    (102, 193,  95),  # green
    (170, 204,  60),  # yellow-green
    (230, 200,  40),  # yellow
    (245, 157,  36),  # orange
    (237,  99,  52),  # orange-red
    (215,  48,  39),  # red         — newest
]
MAX_OVERLAY_DIMENSION = 1800
LEGEND_ROW_HEIGHT = 34
LEGEND_PADDING = 14
LEGEND_SWATCH_SIZE = 14
LEGEND_TEXT_SCALE = 2

DIGIT_FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "?": ("111", "001", "011", "000", "010"),
}


@dataclass
class OverlayResult:
    output_file: Path
    boundary_count: int
    years: list[str]
    base_file: Path


def build_year_boundary_overlay(base: ProcessingOutput, boundaries: list[ProcessingOutput]) -> OverlayResult:
    if not boundaries:
        raise ValueError("Load or create boundary results before building an overlay.")
    if not base.output_file.exists():
        raise FileNotFoundError(f"Base raster does not exist: {base.output_file}")

    usable_boundaries = [item for item in boundaries if item.output_file.exists()]
    if not usable_boundaries:
        raise FileNotFoundError("No boundary raster files are available for overlay.")

    base_ds = gdal.Open(str(base.output_file))
    if base_ds is None:
        raise RuntimeError(f"Could not open base raster: {base.output_file}")
    display_ds = display_dataset(base_ds)

    rgb = render_base_rgb(display_ds)
    year_colors = colors_for_years(sorted({year_for(item) for item in usable_boundaries}))
    for boundary in usable_boundaries:
        mask = boundary_mask(boundary, display_ds)
        if not mask.any():
            continue
        mask = thicken(mask, radius=1)
        color = year_colors[year_for(boundary)]
        for band_index, value in enumerate(color):
            rgb[band_index][mask] = value
    rgb = add_legend(rgb, year_colors)

    output_dir = overlay_dir()
    year_tag = "_".join(year_colors.keys())
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"boundary_overlay_on_{safe_name(base.scene_id)}_{safe_name(year_tag)}_{timestamp}.png"
    write_rgb_png(output_file, rgb)
    return OverlayResult(
        output_file=output_file,
        boundary_count=len(usable_boundaries),
        years=list(year_colors.keys()),
        base_file=base.output_file,
    )


def add_legend(rgb: np.ndarray, year_colors: dict[str, tuple[int, int, int]]) -> np.ndarray:
    if not year_colors:
        return rgb

    height = rgb.shape[1]
    width = rgb.shape[2]
    legend_height = LEGEND_ROW_HEIGHT
    result = np.zeros((3, height + legend_height, width), dtype=np.uint8)
    result[:, :height, :] = rgb
    result[:, height:, :] = 245

    # temporal gradient strip (blue=oldest → red=newest) when more than one year
    colors_list = list(year_colors.values())
    if len(colors_list) > 1:
        strip_x0, strip_x1 = LEGEND_PADDING, width - LEGEND_PADDING
        strip_y0, strip_y1 = height + 3, height + 7
        strip_w = strip_x1 - strip_x0
        if strip_w > 0:
            c0 = np.array(colors_list[0], dtype=np.float32)
            c1 = np.array(colors_list[-1], dtype=np.float32)
            for px in range(strip_w):
                t = px / (strip_w - 1)
                color = (c0 * (1 - t) + c1 * t).astype(np.uint8)
                result[:, strip_y0:strip_y1, strip_x0 + px] = color[:, None]

    x = LEGEND_PADDING
    y = height + (legend_height - LEGEND_SWATCH_SIZE) // 2
    for year, color in year_colors.items():
        item_width = legend_item_width(year)
        if x + item_width > width - LEGEND_PADDING:
            break
        draw_swatch(result, x, y, color)
        draw_text(result, year, x + LEGEND_SWATCH_SIZE + 7, y + 1, (20, 29, 33), LEGEND_TEXT_SCALE)
        x += item_width + 20
    return result


def legend_item_width(text: str) -> int:
    return LEGEND_SWATCH_SIZE + 7 + text_width(text, LEGEND_TEXT_SCALE)


def draw_swatch(rgb: np.ndarray, x: int, y: int, color: tuple[int, int, int]) -> None:
    rgb[:, y : y + LEGEND_SWATCH_SIZE, x : x + LEGEND_SWATCH_SIZE] = np.array(color, dtype=np.uint8)[:, None, None]
    rgb[:, y, x : x + LEGEND_SWATCH_SIZE] = 20
    rgb[:, y + LEGEND_SWATCH_SIZE - 1, x : x + LEGEND_SWATCH_SIZE] = 20
    rgb[:, y : y + LEGEND_SWATCH_SIZE, x] = 20
    rgb[:, y : y + LEGEND_SWATCH_SIZE, x + LEGEND_SWATCH_SIZE - 1] = 20


def draw_text(
    rgb: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    scale: int,
) -> None:
    cursor = x
    for char in text:
        glyph = DIGIT_FONT.get(char, DIGIT_FONT["?"])
        draw_glyph(rgb, glyph, cursor, y, color, scale)
        cursor += (len(glyph[0]) + 1) * scale


def draw_glyph(
    rgb: np.ndarray,
    glyph: tuple[str, ...],
    x: int,
    y: int,
    color: tuple[int, int, int],
    scale: int,
) -> None:
    color_array = np.array(color, dtype=np.uint8)[:, None, None]
    for row_index, row in enumerate(glyph):
        for col_index, value in enumerate(row):
            if value != "1":
                continue
            y0 = y + row_index * scale
            x0 = x + col_index * scale
            rgb[:, y0 : y0 + scale, x0 : x0 + scale] = color_array


def text_width(text: str, scale: int) -> int:
    if not text:
        return 0
    return len(text) * 3 * scale + max(0, len(text) - 1) * scale


def boundary_mask(boundary: ProcessingOutput, base_ds: gdal.Dataset) -> np.ndarray:
    vector_file = boundary.output_file.with_suffix(".geojson")
    if vector_file.exists():
        return rasterized_boundary_mask(vector_file, base_ds)
    return warped_boundary_mask(boundary.output_file, base_ds)


def display_dataset(dataset: gdal.Dataset) -> gdal.Dataset:
    width = dataset.RasterXSize
    height = dataset.RasterYSize
    longest = max(width, height)
    if longest <= MAX_OVERLAY_DIMENSION:
        return dataset

    scale = MAX_OVERLAY_DIMENSION / longest
    out_width = max(1, int(width * scale))
    out_height = max(1, int(height * scale))
    display = gdal.Translate(
        "",
        dataset,
        format="MEM",
        width=out_width,
        height=out_height,
        resampleAlg=gdal.GRA_Bilinear,
    )
    if display is None:
        raise RuntimeError("Could not create reduced-size 2026 overlay base.")
    return display


def best_2026_base(outputs: list[ProcessingOutput]) -> ProcessingOutput | None:
    candidates = [
        item
        for item in outputs
        if item.kind == "Preprocessed"
        and item.scene_id == OVERLAY_BASE_SCENE_ID
        and item.output_file.exists()
    ]
    if not candidates:
        return None
    visual = [item for item in candidates if item.label.lower() == "visual"]
    if visual:
        return sorted(visual, key=lambda item: item.date)[-1]
    preferred = [item for item in candidates if item.label.lower() in {"red", "red b04", "green", "green b03"}]
    if preferred:
        return sorted(preferred, key=lambda item: item.date)[-1]
    return sorted(candidates, key=lambda item: item.date)[-1]


def best_2026_base_from_rows(rows: list[dict[str, str]]) -> ProcessingOutput | None:
    candidates = []
    for row in rows:
        if row.get("item_id", "") != OVERLAY_BASE_SCENE_ID:
            continue
        visual_path = matched_visual_path(row)
        if not visual_path:
            continue
        candidates.append((row_score(row), row, visual_path))

    if not candidates:
        return None

    _score, row, visual_path = min(candidates, key=lambda item: item[0])
    return ProcessingOutput(
        run_name="data_root_target",
        kind="Base",
        label="Target Visual",
        scene_id=row.get("item_id", ""),
        date=row.get("date", ""),
        sensor=row.get("sensor", ""),
        formula="Raw visual raster used as overlay base",
        output_file=visual_path,
    )


def matched_visual_path(row: dict[str, str]) -> Path | None:
    for check in check_scene_bands(row):
        if str(check.get("label", "")).lower() != "visual":
            continue
        matched_path = check.get("matched_path")
        if matched_path:
            path = Path(str(matched_path))
            if path.exists():
                return path
    return None


def row_score(row: dict[str, str]) -> tuple[int, float, str]:
    date = row.get("date", "")
    month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else 0
    summer_penalty = 0 if 6 <= month <= 9 else 1
    return (summer_penalty, float(row.get("cloud_value", 100.0)), date)


def render_base_rgb(dataset: gdal.Dataset) -> np.ndarray:
    band_count = dataset.RasterCount
    if band_count >= 3:
        bands = [scale_to_byte(dataset.GetRasterBand(index).ReadAsArray()) for index in (1, 2, 3)]
    else:
        gray = scale_to_byte(dataset.GetRasterBand(1).ReadAsArray())
        bands = [gray, gray, gray]
    return np.stack(bands, axis=0)


def rasterized_boundary_mask(vector_file: Path, base_ds: gdal.Dataset) -> np.ndarray:
    driver = gdal.GetDriverByName("MEM")
    target = driver.Create("", base_ds.RasterXSize, base_ds.RasterYSize, 1, gdal.GDT_Byte)
    if target is None:
        raise RuntimeError("Could not create in-memory boundary overlay raster.")
    target.SetGeoTransform(base_ds.GetGeoTransform())
    target.SetProjection(base_ds.GetProjection())

    vector = gdal.OpenEx(str(vector_file), gdal.OF_VECTOR)
    if vector is None:
        raise RuntimeError(f"Could not open boundary vector: {vector_file}")
    layer = vector.GetLayer(0)
    err = gdal.RasterizeLayer(target, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    if err != 0:
        raise RuntimeError(f"Could not rasterize boundary vector: {vector_file}")
    return target.GetRasterBand(1).ReadAsArray() > 0


def warped_boundary_mask(boundary_file: Path, base_ds: gdal.Dataset) -> np.ndarray:
    gt = base_ds.GetGeoTransform()
    width = base_ds.RasterXSize
    height = base_ds.RasterYSize
    min_x = gt[0]
    max_y = gt[3]
    max_x = gt[0] + gt[1] * width + gt[2] * height
    min_y = gt[3] + gt[4] * width + gt[5] * height
    bounds = (min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))

    warped = gdal.Warp(
        "",
        str(boundary_file),
        format="MEM",
        width=width,
        height=height,
        outputBounds=bounds,
        dstSRS=base_ds.GetProjection(),
        resampleAlg=gdal.GRA_NearestNeighbour,
    )
    if warped is None:
        raise RuntimeError(f"Could not warp boundary raster: {boundary_file}")
    return warped.GetRasterBand(1).ReadAsArray() > 0


def scale_to_byte(array: np.ndarray) -> np.ndarray:
    values = array.astype(np.float32)
    finite = np.isfinite(values)
    if not finite.any():
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(values[finite], [2, 98])
    if high <= low:
        high = low + 1
    scaled = (values - low) * 255.0 / (high - low)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def thicken(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask
    result = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(mask)
            src_y0 = max(0, -dy)
            src_y1 = mask.shape[0] - max(0, dy)
            src_x0 = max(0, -dx)
            src_x1 = mask.shape[1] - max(0, dx)
            dst_y0 = max(0, dy)
            dst_y1 = mask.shape[0] - max(0, -dy)
            dst_x0 = max(0, dx)
            dst_x1 = mask.shape[1] - max(0, -dx)
            shifted[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
            result |= shifted
    return result


def write_rgb_png(output_file: Path, rgb: np.ndarray) -> None:
    mem_driver = gdal.GetDriverByName("MEM")
    dataset = mem_driver.Create("", rgb.shape[2], rgb.shape[1], 3, gdal.GDT_Byte)
    if dataset is None:
        raise RuntimeError("Could not create in-memory overlay image.")
    for index in range(3):
        dataset.GetRasterBand(index + 1).WriteArray(rgb[index])
    png_driver = gdal.GetDriverByName("PNG")
    png = png_driver.CreateCopy(str(output_file), dataset)
    if png is None:
        raise RuntimeError(f"Could not create overlay PNG: {output_file}")
    png.FlushCache()
    png = None
    dataset = None


def colors_for_years(years: list[str]) -> dict[str, tuple[int, int, int]]:
    return {year: YEAR_COLORS[index % len(YEAR_COLORS)] for index, year in enumerate(years)}


def year_for(output: ProcessingOutput) -> str:
    return output.date[:4] if len(output.date) >= 4 and output.date[:4].isdigit() else "unknown"
