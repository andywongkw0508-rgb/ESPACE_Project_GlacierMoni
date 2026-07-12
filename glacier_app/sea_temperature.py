from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from osgeo import gdal, ogr, osr

from .config import AOI_CONFIG, PREPROCESS_TARGET_CRS, RESULTS_DIR
from .results import dataset_bounds, draw_small_text, write_overlay_metadata, write_rgba_png


OUTPUT_DIR = RESULTS_DIR / "surface_temperature"
TARGET_RESOLUTION_M = 90.0
MIN_COMPONENT_PIXELS = 64
TEMPERATURE_NODATA = -9999.0
SR_SCALE = np.float32(0.0000275)
SR_OFFSET = np.float32(-0.2)
ST_SCALE = np.float32(0.00341802)
ST_OFFSET_K = np.float32(149.0)
KELVIN_TO_CELSIUS = np.float32(273.15)
NDSI_GLACIER_THRESHOLD = np.float32(0.40)
NDWI_WATER_THRESHOLD = np.float32(0.15)
SEA_TEMPERATURE_MIN_C = np.float32(-5.0)
SEA_TEMPERATURE_MAX_C = np.float32(25.0)
GLACIER_TEMPERATURE_MAX_C = np.float32(5.0)
COLOR_MIN_C = -20.0
COLOR_MAX_C = 20.0
OVERLAY_ALPHA = np.float32(0.72)

TEMPERATURE_STOPS = [
    (-20.0, (52, 43, 128)),
    (-10.0, (42, 105, 176)),
    (0.0, (48, 184, 176)),
    (5.0, (226, 207, 67)),
    (10.0, (239, 128, 45)),
    (20.0, (171, 35, 58)),
]

ProgressCallback = Callable[[str], None] | None


@dataclass(frozen=True)
class LandsatTemperatureScene:
    scene_id: str
    date: str
    acquisition_datetime: str
    platform: str
    cloud_cover: float
    planetary_computer_item: str
    matched_sentinel_scene_id: str
    matched_sentinel_datetime: str
    time_gap_minutes: float
    blue_file: Path
    green_file: Path
    red_file: Path
    nir_file: Path
    swir_file: Path
    qa_file: Path


@dataclass(frozen=True)
class TemperatureStatistics:
    mean_c: float
    min_c: float
    max_c: float
    pixel_count: int
    area_km2: float


@dataclass(frozen=True)
class RemoteTemperatureResult:
    scene: LandsatTemperatureScene
    temperature_raster: Path
    class_raster: Path
    figure_file: Path
    metadata_file: Path
    thermal_asset: str
    sea: TemperatureStatistics
    glacier: TemperatureStatistics
    map_width: int
    map_height: int

    def details_text(self) -> str:
        return (
            "Landsat remote-sensing surface-temperature map\n"
            f"Scene ID: {self.scene.scene_id}\n"
            f"Acquisition date: {self.scene.date}\n"
            f"Platform: {self.scene.platform}\n"
            f"Matched Sentinel scene: {self.scene.matched_sentinel_scene_id}\n"
            f"Acquisition time difference: {self.scene.time_gap_minutes:.1f} minutes\n"
            "Thermal product: Collection 2 Level-2 ST_B10\n"
            "Conversion: DN * 0.00341802 + 149.0 K, converted to deg C\n"
            f"Sea temperature: mean {self.sea.mean_c:.2f}, min {self.sea.min_c:.2f}, "
            f"max {self.sea.max_c:.2f} deg C\n"
            f"Glacier temperature: mean {self.glacier.mean_c:.2f}, min {self.glacier.min_c:.2f}, "
            f"max {self.glacier.max_c:.2f} deg C\n"
            f"Sea mapped area: {self.sea.area_km2:.2f} km2\n"
            f"Glacier mapped area: {self.glacier.area_km2:.2f} km2\n"
            "Classification: same-scene QA_PIXEL, NDSI, NDWI, and thermal plausibility filters\n"
            f"Temperature raster: {self.temperature_raster}\n"
            f"Class raster: {self.class_raster}\n"
            f"Map image: {self.figure_file}\n"
            f"Metadata: {self.metadata_file}"
        )


def create_remote_temperature_map(
    scene: LandsatTemperatureScene,
    progress: ProgressCallback = None,
) -> RemoteTemperatureResult:
    gdal.UseExceptions()
    ogr.UseExceptions()
    report(progress, f"Preparing Landsat bands for {scene.scene_id}...")

    reference = warp_to_aoi(scene.blue_file, gdal.GRA_Bilinear)
    projection = reference.GetProjection()
    geotransform = reference.GetGeoTransform()
    bounds = dataset_bounds(reference)
    width, height = reference.RasterXSize, reference.RasterYSize

    blue_dn = reference.GetRasterBand(1).ReadAsArray().astype(np.float32)
    green_dn = aligned_array(scene.green_file, reference, gdal.GRA_Bilinear, nodata=0)
    red_dn = aligned_array(scene.red_file, reference, gdal.GRA_Bilinear, nodata=0)
    nir_dn = aligned_array(scene.nir_file, reference, gdal.GRA_Bilinear, nodata=0)
    swir_dn = aligned_array(scene.swir_file, reference, gdal.GRA_Bilinear, nodata=0)
    qa = aligned_array(scene.qa_file, reference, gdal.GRA_NearestNeighbour).astype(np.uint16)

    report(progress, "Requesting signed Landsat ST_B10 thermal asset...")
    thermal_asset, signed_thermal = signed_thermal_asset(scene.planetary_computer_item)
    thermal_source = open_remote_thermal(signed_thermal)
    thermal_dn = aligned_dataset_array(
        thermal_source,
        reference,
        gdal.GRA_Bilinear,
        nodata=0,
    )
    thermal_source = None
    reference = None

    report(progress, "Converting Landsat thermal DN values to surface temperature...")
    blue = scale_surface_reflectance(blue_dn)
    green = scale_surface_reflectance(green_dn)
    red = scale_surface_reflectance(red_dn)
    nir = scale_surface_reflectance(nir_dn)
    swir = scale_surface_reflectance(swir_dn)
    temperature_c = thermal_dn.astype(np.float32) * ST_SCALE + ST_OFFSET_K - KELVIN_TO_CELSIUS

    spectral_valid = (
        (blue_dn > 0)
        & (green_dn > 0)
        & (red_dn > 0)
        & (nir_dn > 0)
        & (swir_dn > 0)
    )
    thermal_valid = (thermal_dn > 0) & np.isfinite(temperature_c)
    thermal_valid &= (temperature_c >= -80.0) & (temperature_c <= 60.0)
    cloud = quality_cloud_mask(qa)
    valid = spectral_valid & thermal_valid & ~cloud

    ndsi = normalized_difference(green, swir)
    ndwi = normalized_difference(green, nir)
    qa_water = (qa & (1 << 7)) != 0
    qa_snow = (qa & (1 << 5)) != 0

    water_candidate = (
        valid
        & (temperature_c >= SEA_TEMPERATURE_MIN_C)
        & (temperature_c <= SEA_TEMPERATURE_MAX_C)
        & (
            qa_water
            | (
                (ndwi >= NDWI_WATER_THRESHOLD)
                & (nir < np.float32(0.15))
                & (ndsi < NDSI_GLACIER_THRESHOLD)
            )
        )
    )
    sea_mask = retain_largest_component(water_candidate, projection, geotransform) & water_candidate
    glacier_candidate = (
        valid
        & ~sea_mask
        & (temperature_c <= GLACIER_TEMPERATURE_MAX_C)
        & ((ndsi >= NDSI_GLACIER_THRESHOLD) | qa_snow)
    )
    glacier_mask = retain_largest_component(glacier_candidate, projection, geotransform) & glacier_candidate

    if int(sea_mask.sum()) < 100:
        raise RuntimeError(f"No usable coastal sea-temperature pixels were found for {scene.scene_id}.")
    if int(glacier_mask.sum()) < 100:
        raise RuntimeError(f"No usable glacier-temperature pixels were found for {scene.scene_id}.")

    pixel_area_m2 = abs(geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4])
    sea_stats = temperature_statistics(temperature_c, sea_mask, pixel_area_m2)
    glacier_stats = temperature_statistics(temperature_c, glacier_mask, pixel_area_m2)

    output_dir = result_directory(scene)
    stem = f"{safe_name(scene.scene_id)}_Landsat_ST_B10_{time.strftime('%Y%m%d_%H%M%S')}"
    temperature_raster = output_dir / f"{stem}_temperature_C.tif"
    class_raster = output_dir / f"{stem}_classes.tif"
    figure_file = output_dir / f"{stem}_map.png"
    metadata_file = output_dir / f"{stem}_metadata.json"

    report(progress, "Writing sea and glacier surface-temperature rasters...")
    class_values = np.zeros((height, width), dtype=np.uint8)
    class_values[sea_mask] = 1
    class_values[glacier_mask] = 2
    mapped = sea_mask | glacier_mask
    write_temperature_raster(
        temperature_raster,
        temperature_c,
        mapped,
        projection,
        geotransform,
        scene,
    )
    write_class_raster(class_raster, class_values, projection, geotransform)

    report(progress, "Rendering remote-sensing temperature map...")
    base_rgb = render_base_rgb(red, green, blue, spectral_valid)
    render_temperature_map(
        figure_file,
        base_rgb,
        spectral_valid,
        temperature_c,
        mapped,
        sea_stats,
        glacier_stats,
    )
    write_overlay_metadata(figure_file, width, height)
    write_metadata(
        metadata_file,
        scene,
        thermal_asset,
        temperature_raster,
        class_raster,
        figure_file,
        sea_stats,
        glacier_stats,
        width,
        height,
    )
    report(progress, f"Remote-sensing temperature map complete: {figure_file.name}")

    return RemoteTemperatureResult(
        scene=scene,
        temperature_raster=temperature_raster,
        class_raster=class_raster,
        figure_file=figure_file,
        metadata_file=metadata_file,
        thermal_asset=thermal_asset,
        sea=sea_stats,
        glacier=glacier_stats,
        map_width=width,
        map_height=height,
    )


def warp_to_aoi(path: Path, resample_alg: int) -> gdal.Dataset:
    source = gdal.Open(str(path))
    if source is None:
        raise RuntimeError(f"Could not open Landsat band: {path}")
    bbox = read_aoi_bbox()
    dataset = gdal.Warp(
        "",
        source,
        format="MEM",
        dstSRS=PREPROCESS_TARGET_CRS,
        outputBounds=(bbox[0], bbox[1], bbox[2], bbox[3]),
        outputBoundsSRS="EPSG:4326",
        xRes=TARGET_RESOLUTION_M,
        yRes=TARGET_RESOLUTION_M,
        targetAlignedPixels=True,
        resampleAlg=resample_alg,
        srcNodata=0,
        dstNodata=0,
    )
    source = None
    if dataset is None:
        raise RuntimeError(f"Could not clip Landsat band to the project AOI: {path}")
    return dataset


def aligned_array(
    path: Path,
    reference: gdal.Dataset,
    resample_alg: int,
    nodata: int | None = None,
) -> np.ndarray:
    source = gdal.Open(str(path))
    if source is None:
        raise RuntimeError(f"Could not open Landsat band: {path}")
    result = aligned_dataset_array(source, reference, resample_alg, nodata)
    source = None
    return result


def aligned_dataset_array(
    source: gdal.Dataset,
    reference: gdal.Dataset,
    resample_alg: int,
    nodata: int | None = None,
) -> np.ndarray:
    options: dict[str, object] = {
        "format": "MEM",
        "width": reference.RasterXSize,
        "height": reference.RasterYSize,
        "outputBounds": dataset_bounds(reference),
        "dstSRS": reference.GetProjection(),
        "resampleAlg": resample_alg,
    }
    if nodata is not None:
        options["srcNodata"] = nodata
        options["dstNodata"] = nodata
    aligned = gdal.Warp("", source, **options)
    if aligned is None:
        raise RuntimeError("Could not align a Landsat temperature input to the AOI grid.")
    array = aligned.GetRasterBand(1).ReadAsArray()
    aligned = None
    return array


def signed_thermal_asset(item_url: str) -> tuple[str, str]:
    item = fetch_json(item_url)
    assets = item.get("assets", {})
    asset = assets.get("lwir11") or assets.get("ST_B10")
    if not isinstance(asset, dict) or not asset.get("href"):
        raise RuntimeError("The selected Landsat item does not provide an ST_B10 thermal asset.")
    href = str(asset["href"])
    sign_url = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?" + urllib.parse.urlencode(
        {"href": href}
    )
    signed = fetch_json(sign_url).get("href")
    if not signed:
        raise RuntimeError("Planetary Computer did not return a signed ST_B10 URL.")
    return href, str(signed)


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ESPACE-GlacierMoni/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except Exception as exc:
        raise RuntimeError(f"Could not access Landsat remote-sensing metadata: {exc}") from exc


def open_remote_thermal(signed_url: str) -> gdal.Dataset:
    gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")
    gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "1")
    gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "60")
    dataset = gdal.Open(f"/vsicurl/{signed_url}")
    if dataset is None:
        raise RuntimeError("Could not stream the signed Landsat ST_B10 thermal COG.")
    return dataset


def read_aoi_bbox() -> tuple[float, float, float, float]:
    with AOI_CONFIG.open(encoding="utf-8") as handle:
        bbox = json.load(handle)["bbox"]
    return float(bbox["west"]), float(bbox["south"]), float(bbox["east"]), float(bbox["north"])


def scale_surface_reflectance(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) * SR_SCALE + SR_OFFSET


def normalized_difference(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    denominator = left + right
    result = np.full(left.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(left) & np.isfinite(right) & (np.abs(denominator) > np.float32(1e-6))
    result[valid] = (left[valid] - right[valid]) / denominator[valid]
    return result


def quality_cloud_mask(qa: np.ndarray) -> np.ndarray:
    mask = np.zeros(qa.shape, dtype=bool)
    for bit in (0, 1, 2, 3, 4):
        mask |= (qa & (1 << bit)) != 0
    return dilate(mask, radius=1)


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0 or not mask.any():
        return mask
    result = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
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


def retain_largest_component(
    mask: np.ndarray,
    projection: str,
    geotransform: tuple[float, float, float, float, float, float],
) -> np.ndarray:
    if not mask.any():
        return mask
    raster_driver = gdal.GetDriverByName("MEM")
    source = raster_driver.Create("", mask.shape[1], mask.shape[0], 1, gdal.GDT_Byte)
    sieved = raster_driver.Create("", mask.shape[1], mask.shape[0], 1, gdal.GDT_Byte)
    source.SetGeoTransform(geotransform)
    source.SetProjection(projection)
    sieved.SetGeoTransform(geotransform)
    sieved.SetProjection(projection)
    source.GetRasterBand(1).WriteArray(mask.astype(np.uint8))
    gdal.SieveFilter(
        source.GetRasterBand(1),
        None,
        sieved.GetRasterBand(1),
        MIN_COMPONENT_PIXELS,
        8,
    )

    spatial_ref = osr.SpatialReference()
    if projection:
        spatial_ref.ImportFromWkt(projection)
    vector_driver = ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")
    datasource = vector_driver.CreateDataSource("")
    layer = datasource.CreateLayer("components", spatial_ref, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    band = sieved.GetRasterBand(1)
    gdal.Polygonize(band, band, layer, 0, [], callback=None)

    largest = None
    largest_area = 0.0
    layer.ResetReading()
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if feature.GetField("value") != 1 or geometry is None:
            continue
        area = float(geometry.GetArea())
        if area > largest_area:
            largest_area = area
            largest = geometry.Clone()
    if largest is None:
        return np.zeros(mask.shape, dtype=bool)

    selected_source = vector_driver.CreateDataSource("")
    selected_layer = selected_source.CreateLayer("selected", spatial_ref, ogr.wkbPolygon)
    feature = ogr.Feature(selected_layer.GetLayerDefn())
    feature.SetGeometry(largest)
    selected_layer.CreateFeature(feature)
    target = raster_driver.Create("", mask.shape[1], mask.shape[0], 1, gdal.GDT_Byte)
    target.SetGeoTransform(geotransform)
    target.SetProjection(projection)
    target.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(target, [1], selected_layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    result = target.GetRasterBand(1).ReadAsArray().astype(bool)
    datasource = None
    selected_source = None
    source = None
    sieved = None
    target = None
    return result


def temperature_statistics(
    temperature_c: np.ndarray,
    mask: np.ndarray,
    pixel_area_m2: float,
) -> TemperatureStatistics:
    values = temperature_c[mask & np.isfinite(temperature_c)]
    if values.size == 0:
        raise RuntimeError("Temperature statistics could not be calculated for an empty class.")
    return TemperatureStatistics(
        mean_c=float(np.mean(values)),
        min_c=float(np.min(values)),
        max_c=float(np.max(values)),
        pixel_count=int(values.size),
        area_km2=float(values.size * pixel_area_m2 / 1_000_000.0),
    )


def render_base_rgb(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    return np.stack(
        [scale_display_band(red, valid), scale_display_band(green, valid), scale_display_band(blue, valid)],
        axis=0,
    )


def scale_display_band(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    result = np.zeros(values.shape, dtype=np.uint8)
    sample = values[valid & np.isfinite(values)]
    if sample.size == 0:
        return result
    low, high = np.percentile(sample, [2.0, 98.0])
    if high <= low:
        high = low + 1.0
    scaled = (values - np.float32(low)) * np.float32(255.0 / (high - low))
    result[valid] = np.clip(scaled[valid], 0, 255).astype(np.uint8)
    return result


def render_temperature_map(
    output_file: Path,
    base_rgb: np.ndarray,
    base_valid: np.ndarray,
    temperature_c: np.ndarray,
    mapped: np.ndarray,
    sea: TemperatureStatistics,
    glacier: TemperatureStatistics,
) -> None:
    overlay = temperature_rgb(temperature_c)
    rgb = base_rgb.astype(np.float32)
    for index in range(3):
        rgb[index][mapped] = (
            rgb[index][mapped] * (np.float32(1.0) - OVERLAY_ALPHA)
            + overlay[index][mapped].astype(np.float32) * OVERLAY_ALPHA
        )
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    alpha = np.where(base_valid, np.uint8(255), np.uint8(0))
    canvas, canvas_alpha = add_legend(rgb, alpha, sea, glacier)
    write_rgba_png(output_file, canvas, canvas_alpha)


def temperature_rgb(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(np.float32), COLOR_MIN_C, COLOR_MAX_C)
    result = np.zeros((3, values.shape[0], values.shape[1]), dtype=np.uint8)
    for (low, low_color), (high, high_color) in zip(TEMPERATURE_STOPS, TEMPERATURE_STOPS[1:]):
        selected = (clipped >= low) & (clipped <= high)
        fraction = np.zeros(values.shape, dtype=np.float32)
        fraction[selected] = (clipped[selected] - np.float32(low)) / np.float32(high - low)
        for band_index in range(3):
            channel = low_color[band_index] * (1.0 - fraction) + high_color[band_index] * fraction
            result[band_index][selected] = np.clip(channel[selected], 0, 255).astype(np.uint8)
    return result


def temperature_color(value: float) -> tuple[int, int, int]:
    array = temperature_rgb(np.array([[value]], dtype=np.float32))
    return int(array[0, 0, 0]), int(array[1, 0, 0]), int(array[2, 0, 0])


def add_legend(
    rgb: np.ndarray,
    alpha: np.ndarray,
    sea: TemperatureStatistics,
    glacier: TemperatureStatistics,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = rgb.shape[1], rgb.shape[2]
    panel_width = 240
    canvas = np.full((3, height, width + panel_width), np.uint8(245), dtype=np.uint8)
    canvas[:, :, :width] = rgb
    canvas_alpha = np.full((height, width + panel_width), np.uint8(255), dtype=np.uint8)
    canvas_alpha[:, :width] = alpha
    canvas[:, :, width : width + 1] = 145

    text_x = width + 18
    scale = 2 if height >= 650 else 1
    draw_small_text(canvas, "THERMAL MAP", text_x, 20, (20, 29, 33), scale)
    draw_small_text(canvas, "LANDSAT ST B10", text_x, 50, (72, 86, 94), 1)
    draw_small_text(canvas, "RGB NO TEMP", text_x, 70, (92, 100, 104), 1)

    bar_x0 = width + 24
    bar_x1 = bar_x0 + 34
    bar_y0 = 96
    bar_y1 = max(bar_y0 + 80, height - 150)
    for y in range(bar_y0, bar_y1):
        fraction = (y - bar_y0) / max(1, bar_y1 - bar_y0 - 1)
        value = COLOR_MAX_C - fraction * (COLOR_MAX_C - COLOR_MIN_C)
        canvas[:, y, bar_x0:bar_x1] = np.array(temperature_color(value), dtype=np.uint8)[:, None]
    canvas[:, bar_y0, bar_x0:bar_x1] = 20
    canvas[:, bar_y1 - 1, bar_x0:bar_x1] = 20
    canvas[:, bar_y0:bar_y1, bar_x0] = 20
    canvas[:, bar_y0:bar_y1, bar_x1 - 1] = 20

    label_x = bar_x1 + 12
    for value in (20.0, 10.0, 0.0, -10.0, -20.0):
        fraction = (COLOR_MAX_C - value) / (COLOR_MAX_C - COLOR_MIN_C)
        y = int(round(bar_y0 + fraction * (bar_y1 - bar_y0 - 1)))
        draw_small_text(canvas, f"{value:.0f}", label_x, y - 3, (20, 29, 33), 1)

    stats_y = max(10, height - 104)
    draw_small_text(canvas, f"SEA {sea.mean_c:.1f} C", text_x, stats_y, (20, 29, 33), 1)
    draw_small_text(canvas, f"ICE {glacier.mean_c:.1f} C", text_x, stats_y + 22, (20, 29, 33), 1)
    draw_small_text(canvas, "MEAN TEMP", text_x, stats_y + 49, (72, 86, 94), 1)
    return canvas, canvas_alpha


def write_temperature_raster(
    path: Path,
    temperature_c: np.ndarray,
    mapped: np.ndarray,
    projection: str,
    geotransform: tuple[float, float, float, float, float, float],
    scene: LandsatTemperatureScene,
) -> None:
    values = np.full(temperature_c.shape, np.float32(TEMPERATURE_NODATA), dtype=np.float32)
    values[mapped] = temperature_c[mapped]
    dataset = create_tiff(path, values.shape[1], values.shape[0], gdal.GDT_Float32)
    dataset.SetGeoTransform(geotransform)
    dataset.SetProjection(projection)
    dataset.SetMetadataItem("SOURCE", "Landsat Collection 2 Level-2 ST_B10")
    dataset.SetMetadataItem("SCENE_ID", scene.scene_id)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(TEMPERATURE_NODATA)
    band.SetDescription("Sea and glacier surface temperature")
    band.SetUnitType("deg C")
    band.WriteArray(values)
    dataset.FlushCache()
    dataset = None


def write_class_raster(
    path: Path,
    values: np.ndarray,
    projection: str,
    geotransform: tuple[float, float, float, float, float, float],
) -> None:
    dataset = create_tiff(path, values.shape[1], values.shape[0], gdal.GDT_Byte)
    dataset.SetGeoTransform(geotransform)
    dataset.SetProjection(projection)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.SetDescription("Temperature surface class")
    band.SetCategoryNames(["NoData", "Sea", "Glacier"])
    band.SetMetadata(
        {
            "CLASS_0": "NoData or cloud masked",
            "CLASS_1": "Sea",
            "CLASS_2": "Glacier",
        }
    )
    band.WriteArray(values)
    dataset.FlushCache()
    dataset = None


def create_tiff(path: Path, width: int, height: int, data_type: int) -> gdal.Dataset:
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path),
        width,
        height,
        1,
        data_type,
        options=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    if dataset is None:
        raise RuntimeError(f"Could not create temperature output: {path}")
    return dataset


def result_directory(scene: LandsatTemperatureScene) -> Path:
    year = scene.date[:4] if len(scene.date) >= 4 else "unknown_year"
    path = OUTPUT_DIR / year / safe_name(scene.scene_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_metadata(
    path: Path,
    scene: LandsatTemperatureScene,
    thermal_asset: str,
    temperature_raster: Path,
    class_raster: Path,
    figure_file: Path,
    sea: TemperatureStatistics,
    glacier: TemperatureStatistics,
    width: int,
    height: int,
) -> None:
    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": "Landsat Collection 2 Level-2 ST_B10 surface temperature",
        "temperature_conversion": "C = DN * 0.00341802 + 149.0 - 273.15",
        "classification": (
            "QA_PIXEL water/snow/cloud flags plus NDSI, NDWI, and surface-temperature "
            "plausibility filters"
        ),
        "classification_temperature_limits_c": {
            "sea_min": float(SEA_TEMPERATURE_MIN_C),
            "sea_max": float(SEA_TEMPERATURE_MAX_C),
            "glacier_max": float(GLACIER_TEMPERATURE_MAX_C),
        },
        "class_values": {
            "0": "NoData, land, or cloud masked",
            "1": "Sea",
            "2": "Glacier",
        },
        "scene_id": scene.scene_id,
        "date": scene.date,
        "acquisition_datetime": scene.acquisition_datetime,
        "platform": scene.platform,
        "cloud_cover": scene.cloud_cover,
        "matched_sentinel_scene_id": scene.matched_sentinel_scene_id,
        "matched_sentinel_datetime": scene.matched_sentinel_datetime,
        "time_gap_minutes": scene.time_gap_minutes,
        "planetary_computer_item": scene.planetary_computer_item,
        "thermal_asset": thermal_asset,
        "temperature_raster": str(temperature_raster),
        "class_raster": str(class_raster),
        "figure_file": str(figure_file),
        "map_width": width,
        "map_height": height,
        "sea": statistics_dict(sea),
        "glacier": statistics_dict(glacier),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def statistics_dict(stats: TemperatureStatistics) -> dict[str, float | int]:
    return {
        "mean_c": stats.mean_c,
        "min_c": stats.min_c,
        "max_c": stats.max_c,
        "pixel_count": stats.pixel_count,
        "area_km2": stats.area_km2,
    }


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "unnamed"


def report(progress: ProgressCallback, message: str) -> None:
    if progress is not None:
        progress(message)
