from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from osgeo import gdal
from PIL import Image, ImageDraw, ImageFont


PROJECT_BOUNDARY_COLOR = (0, 196, 230)
REFERENCE_BOUNDARY_COLOR = (235, 58, 132)
BOUNDARY_HALO_COLOR = (20, 29, 33)
LEGEND_BACKGROUND = (247, 249, 250, 255)
LEGEND_HEIGHT = 48
RENDER_VERSION = 2


def build_project_reference_boundary_overlay(
    base_image: Path,
    project_boundary_raster: Path,
    reference_geojson: Path,
    output_file: Path,
) -> Path:
    project_boundary_vector = project_boundary_raster.with_suffix(".geojson")
    sources = [base_image, project_boundary_raster, reference_geojson]
    if project_boundary_vector.exists():
        sources.append(project_boundary_vector)
    missing = [path for path in sources if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Boundary validation source is missing: {missing[0]}")

    newest_source = max(path.stat().st_mtime for path in sources)
    metadata_file = output_file.with_suffix(output_file.suffix + ".json")
    if (
        output_file.exists()
        and metadata_file.exists()
        and output_file.stat().st_mtime >= newest_source
        and _cache_matches(metadata_file, base_image)
    ):
        return output_file

    gdal.UseExceptions()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(base_image).convert("RGBA")
    map_array = np.asarray(image, dtype=np.uint8).copy()
    height, width = map_array.shape[:2]

    project_dataset = gdal.Open(str(project_boundary_raster))
    if project_dataset is None:
        raise RuntimeError(f"Could not open project boundary: {project_boundary_raster}")
    bounds = _dataset_bounds(project_dataset)
    projection = project_dataset.GetProjection()
    project_mask = _aligned_project_boundary_mask(
        project_dataset,
        project_boundary_vector,
        bounds,
        projection,
        width,
        height,
    )
    project_dataset = None
    reference_mask = _reference_boundary_mask(
        reference_geojson,
        bounds,
        projection,
        width,
        height,
    )

    rgb = map_array[:, :, :3]
    if "boundary_overlay" in base_image.stem:
        old_project_yellow = (
            (rgb[:, :, 0] >= 220)
            & (rgb[:, :, 1] >= 180)
            & (rgb[:, :, 2] <= 110)
        )
        project_mask |= old_project_yellow
    project_mask = _thicken(project_mask, radius=1)
    reference_mask = _thicken(reference_mask, radius=1)
    _draw_mask(rgb, project_mask, PROJECT_BOUNDARY_COLOR)
    _draw_mask(rgb, reference_mask, REFERENCE_BOUNDARY_COLOR)
    map_image = Image.fromarray(map_array)
    result = _add_legend(map_image)
    result.save(output_file)

    metadata = {
        "render_version": RENDER_VERSION,
        "coordinate_region": [0, 0, width, height],
        "base_image": str(base_image),
        "project_boundary": {
            "source": str(
                project_boundary_vector
                if project_boundary_vector.exists()
                else project_boundary_raster
            ),
            "color": _hex(PROJECT_BOUNDARY_COLOR),
            "processing": "rasterized to the display grid",
        },
        "reference_boundary": {
            "source": str(reference_geojson),
            "color": _hex(REFERENCE_BOUNDARY_COLOR),
            "source_dates": "1999-2003",
            "processing": [
                "geometry repaired in memory",
                "reprojected to project CRS",
                "clipped to displayed raster extent",
                "union rasterized for display",
            ],
            "raw_reference_modified": False,
        },
    }
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return output_file


def _cache_matches(metadata_file: Path, base_image: Path) -> bool:
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        metadata.get("render_version") == RENDER_VERSION
        and metadata.get("base_image") == str(base_image)
    )


def _aligned_project_boundary_mask(
    dataset: gdal.Dataset,
    vector_file: Path,
    bounds: tuple[float, float, float, float],
    projection: str,
    width: int,
    height: int,
) -> np.ndarray:
    if vector_file.exists():
        vector = gdal.VectorTranslate(
            "",
            str(vector_file),
            format="MEM",
            dstSRS=projection,
            makeValid=True,
        )
        if vector is None:
            raise RuntimeError(f"Could not prepare project boundary: {vector_file}")
        target = _empty_mask_dataset(bounds, projection, width, height)
        error = gdal.RasterizeLayer(
            target,
            [1],
            vector.GetLayer(0),
            burn_values=[1],
            options=["ALL_TOUCHED=TRUE"],
        )
        vector = None
        if error != 0:
            raise RuntimeError(f"Could not rasterize project boundary: {vector_file}")
        mask = target.GetRasterBand(1).ReadAsArray() > 0
        target = None
        return np.asarray(mask, dtype=bool)

    reduced = gdal.Warp(
        "",
        dataset,
        format="MEM",
        width=width,
        height=height,
        outputBounds=bounds,
        dstSRS=projection,
        srcNodata=0,
        dstNodata=0,
        resampleAlg=getattr(gdal, "GRA_Max", gdal.GRA_NearestNeighbour),
    )
    if reduced is None:
        raise RuntimeError("Could not align the project boundary for validation.")
    mask = reduced.GetRasterBand(1).ReadAsArray() > 0
    reduced = None
    return np.asarray(mask, dtype=bool)


def _reference_boundary_mask(
    reference_geojson: Path,
    bounds: tuple[float, float, float, float],
    projection: str,
    width: int,
    height: int,
) -> np.ndarray:
    vector = gdal.VectorTranslate(
        "",
        str(reference_geojson),
        format="MEM",
        dstSRS=projection,
        makeValid=True,
        where="line_type = 'glac_bound'",
    )
    if vector is None:
        raise RuntimeError(f"Could not prepare GLIMS reference: {reference_geojson}")

    target = _empty_mask_dataset(bounds, projection, width, height)
    error = gdal.RasterizeLayer(
        target,
        [1],
        vector.GetLayer(0),
        burn_values=[1],
        options=["ALL_TOUCHED=TRUE"],
    )
    vector = None
    if error != 0:
        raise RuntimeError("Could not rasterize the GLIMS reference boundary.")
    filled = target.GetRasterBand(1).ReadAsArray() > 0
    target = None
    return _outline(np.asarray(filled, dtype=bool))


def _empty_mask_dataset(
    bounds: tuple[float, float, float, float],
    projection: str,
    width: int,
    height: int,
) -> gdal.Dataset:
    target = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    if target is None:
        raise RuntimeError("Could not create a boundary validation raster.")
    target.SetGeoTransform(
        (
            bounds[0],
            (bounds[2] - bounds[0]) / width,
            0.0,
            bounds[3],
            0.0,
            -(bounds[3] - bounds[1]) / height,
        )
    )
    target.SetProjection(projection)
    return target


def _outline(mask: np.ndarray) -> np.ndarray:
    interior = mask.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        interior &= _shift(mask, dy, dx)
    return mask & ~interior


def _thicken(mask: np.ndarray, radius: int) -> np.ndarray:
    result = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            result |= _shift(mask, dy, dx)
    return result


def _shift(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
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
    return shifted


def _draw_mask(rgb: np.ndarray, mask: np.ndarray, color: tuple[int, int, int]) -> None:
    halo = _thicken(mask, radius=1)
    rgb[halo] = BOUNDARY_HALO_COLOR
    rgb[mask] = color


def _add_legend(image: Image.Image) -> Image.Image:
    width, height = image.size
    result = Image.new("RGBA", (width, height + LEGEND_HEIGHT), LEGEND_BACKGROUND)
    result.paste(image, (0, 0))
    draw = ImageDraw.Draw(result)
    font = _legend_font(15)
    small_font = _legend_font(12)
    y = height + 14
    first_x = 18
    second_x = min(width // 2, 350)
    _draw_legend_item(draw, first_x, y, PROJECT_BOUNDARY_COLOR, "Project-generated boundary", font)
    _draw_legend_item(
        draw,
        second_x,
        y,
        REFERENCE_BOUNDARY_COLOR,
        "GLIMS reference (1999-2003)",
        font,
    )
    warning = "Historical comparison; raw reference unchanged"
    warning_width = draw.textlength(warning, font=small_font)
    warning_x = max(second_x + 280, width - int(warning_width) - 18)
    if warning_x + warning_width <= width - 8:
        draw.text((warning_x, height + 16), warning, fill=(84, 98, 105), font=small_font)
    return result


def _draw_legend_item(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    color: tuple[int, int, int],
    text: str,
    font: ImageFont.ImageFont,
) -> None:
    draw.line((x, y + 8, x + 28, y + 8), fill=BOUNDARY_HALO_COLOR, width=7)
    draw.line((x, y + 8, x + 28, y + 8), fill=color, width=4)
    draw.text((x + 38, y), text, fill=(31, 45, 51), font=font)


def _legend_font(size: int) -> ImageFont.ImageFont:
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _dataset_bounds(dataset: gdal.Dataset) -> tuple[float, float, float, float]:
    transform = dataset.GetGeoTransform()
    width = dataset.RasterXSize
    height = dataset.RasterYSize
    corners = (
        _transform_pixel(transform, 0, 0),
        _transform_pixel(transform, width, 0),
        _transform_pixel(transform, width, height),
        _transform_pixel(transform, 0, height),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _transform_pixel(
    transform: tuple[float, float, float, float, float, float],
    pixel_x: int,
    pixel_y: int,
) -> tuple[float, float]:
    x = transform[0] + pixel_x * transform[1] + pixel_y * transform[2]
    y = transform[3] + pixel_x * transform[4] + pixel_y * transform[5]
    return x, y


def _hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02X}" for value in color)
