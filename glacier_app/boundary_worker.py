from __future__ import annotations

import json
import os
import sys

import numpy as np
from osgeo import gdal, ogr, osr


MIN_REGION_PIXELS = 1500
SMOOTHING_ITERATIONS = 2
SIMPLIFY_PIXELS = 1.5
POLYGONIZE_MAX_DIM = 2000  # decimate to this before polygonizing


def compute(mask_path: str, boundary_raster_path: str, polygon_path: str, boundary_path: str) -> dict[str, float | int]:
    gdal.UseExceptions()
    ogr.UseExceptions()

    source = gdal.Open(mask_path)
    if source is None:
        raise RuntimeError(f"Could not open mask raster: {mask_path}")

    band = source.GetRasterBand(1)
    original_mask = band.ReadAsArray().astype(bool)
    refined_mask = refine_mask(original_mask)
    refined_source = mask_dataset(source, refined_mask)
    boundary = boundary_pixels(refined_mask).astype(np.uint8)

    write_boundary_raster(source, boundary, boundary_raster_path)
    polygon_count = polygonize_mask(refined_source, polygon_path)
    boundary_count, length_m = write_boundary_vectors(polygon_path, boundary_path)

    return {
        "source_pixels": int(original_mask.sum()),
        "refined_pixels": int(refined_mask.sum()),
        "boundary_pixels": int(boundary.sum()),
        "polygon_count": int(polygon_count),
        "boundary_count": int(boundary_count),
        "boundary_length_m": float(length_m),
        "boundary_length_km": float(length_m / 1000),
    }


def refine_mask(mask: np.ndarray) -> np.ndarray:
    if mask.size == 0:
        return mask

    refined = majority_filter(mask, iterations=1)
    refined = sieve_mask(refined, MIN_REGION_PIXELS)
    refined = majority_filter(refined, iterations=SMOOTHING_ITERATIONS)
    refined = sieve_mask(refined, MIN_REGION_PIXELS)
    if not refined.any() and mask.any():
        return mask
    return refined


def majority_filter(mask: np.ndarray, iterations: int) -> np.ndarray:
    refined = mask.astype(bool)
    for _iteration in range(iterations):
        padded = np.pad(refined, 1, mode="edge")
        count = (
            padded[:-2, :-2].astype(np.uint8)
            + padded[:-2, 1:-1].astype(np.uint8)
            + padded[:-2, 2:].astype(np.uint8)
            + padded[1:-1, :-2].astype(np.uint8)
            + padded[1:-1, 1:-1].astype(np.uint8)
            + padded[1:-1, 2:].astype(np.uint8)
            + padded[2:, :-2].astype(np.uint8)
            + padded[2:, 1:-1].astype(np.uint8)
            + padded[2:, 2:].astype(np.uint8)
        )
        refined = count >= 5
    return refined


def sieve_mask(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    source = array_dataset(mask.astype(np.uint8))
    target = array_dataset(np.zeros(mask.shape, dtype=np.uint8))
    err = gdal.SieveFilter(
        source.GetRasterBand(1),
        None,
        target.GetRasterBand(1),
        minimum_pixels,
        8,
    )
    if err != 0:
        raise RuntimeError("GDAL sieve filtering failed while refining mask.")
    return target.GetRasterBand(1).ReadAsArray().astype(bool)


def array_dataset(array: np.ndarray) -> gdal.Dataset:
    driver = gdal.GetDriverByName("MEM")
    dataset = driver.Create("", array.shape[1], array.shape[0], 1, gdal.GDT_Byte)
    if dataset is None:
        raise RuntimeError("Could not create in-memory raster.")
    dataset.GetRasterBand(1).WriteArray(array)
    return dataset


def mask_dataset(source: gdal.Dataset, mask: np.ndarray) -> gdal.Dataset:
    dataset = array_dataset(mask.astype(np.uint8))
    dataset.SetGeoTransform(source.GetGeoTransform())
    dataset.SetProjection(source.GetProjection())
    return dataset


def boundary_pixels(mask: np.ndarray) -> np.ndarray:
    if mask.size == 0:
        return mask

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    center = padded[1:-1, 1:-1]
    neighbors = (
        padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
        & padded[:-2, :-2]
        & padded[:-2, 2:]
        & padded[2:, :-2]
        & padded[2:, 2:]
    )
    return center & ~neighbors


def write_boundary_raster(source: gdal.Dataset, boundary: np.ndarray, output_path: str) -> None:
    driver = gdal.GetDriverByName("GTiff")
    target = driver.Create(
        output_path,
        source.RasterXSize,
        source.RasterYSize,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW", "PREDICTOR=2", "TILED=YES"],
    )
    if target is None:
        raise RuntimeError(f"Could not create boundary raster: {output_path}")

    target.SetGeoTransform(source.GetGeoTransform())
    target.SetProjection(source.GetProjection())
    out_band = target.GetRasterBand(1)
    out_band.SetNoDataValue(0)
    out_band.WriteArray(boundary)
    target.FlushCache()


def _decimate_for_polygonize(source: gdal.Dataset) -> gdal.Dataset:
    """Return a decimated copy when the raster is too large for fast polygonization."""
    max_dim = max(source.RasterXSize, source.RasterYSize)
    if max_dim <= POLYGONIZE_MAX_DIM:
        return source
    scale = POLYGONIZE_MAX_DIM / max_dim
    w = max(1, int(source.RasterXSize * scale))
    h = max(1, int(source.RasterYSize * scale))
    ds = gdal.Warp("", source, format="MEM", width=w, height=h,
                   resampleAlg=gdal.GRA_NearestNeighbour)
    if ds is None:
        return source
    return ds


def polygonize_mask(source: gdal.Dataset, output_path: str) -> int:
    work = _decimate_for_polygonize(source)
    driver = ogr.GetDriverByName("GeoJSON")
    if driver is None:
        raise RuntimeError("GeoJSON driver is not available in GDAL/OGR.")
    if os.path.exists(output_path):
        driver.DeleteDataSource(output_path)
    datasource = driver.CreateDataSource(output_path)
    if datasource is None:
        raise RuntimeError(f"Could not create polygon output: {output_path}")

    spatial_ref = spatial_reference_for(source)
    layer = datasource.CreateLayer("glacier_mask", spatial_ref, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))

    band = work.GetRasterBand(1)
    gdal.Polygonize(band, band, layer, 0, [], callback=None)

    layer.ResetReading()
    kept = 0
    for feature in list(layer):
        if feature.GetField("value") != 1:
            layer.DeleteFeature(feature.GetFID())
            continue
        geometry = feature.GetGeometryRef()
        if geometry is not None:
            simplified = simplify_geometry(geometry, work)
            feature.SetGeometry(simplified)
            feature.SetField("area_m2", float(simplified.GetArea()))
            layer.SetFeature(feature)
        kept += 1

    datasource = None
    return kept


def simplify_geometry(geometry: ogr.Geometry, source: gdal.Dataset) -> ogr.Geometry:
    tolerance = pixel_size(source) * SIMPLIFY_PIXELS
    if tolerance <= 0:
        return geometry.Clone()
    simplified = geometry.SimplifyPreserveTopology(tolerance)
    return simplified if simplified is not None else geometry.Clone()


def pixel_size(dataset: gdal.Dataset) -> float:
    geotransform = dataset.GetGeoTransform()
    x_size = (geotransform[1] ** 2 + geotransform[4] ** 2) ** 0.5
    y_size = (geotransform[2] ** 2 + geotransform[5] ** 2) ** 0.5
    return max(x_size, y_size)


def write_boundary_vectors(polygon_path: str, output_path: str) -> tuple[int, float]:
    source = ogr.Open(polygon_path)
    if source is None:
        raise RuntimeError(f"Could not open polygon output: {polygon_path}")
    source_layer = source.GetLayer(0)
    source_layer.ResetReading()

    driver = ogr.GetDriverByName("GeoJSON")
    if os.path.exists(output_path):
        driver.DeleteDataSource(output_path)
    target = driver.CreateDataSource(output_path)
    if target is None:
        raise RuntimeError(f"Could not create boundary output: {output_path}")

    target_layer = target.CreateLayer(
        "glacier_boundary",
        source_layer.GetSpatialRef(),
        ogr.wkbUnknown,
    )
    target_layer.CreateField(ogr.FieldDefn("source_fid", ogr.OFTInteger))
    target_layer.CreateField(ogr.FieldDefn("length_m", ogr.OFTReal))

    count = 0
    total_length = 0.0
    for feature in source_layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        boundary = geometry.Boundary()
        if boundary is None:
            continue
        length = float(boundary.Length())
        out_feature = ogr.Feature(target_layer.GetLayerDefn())
        out_feature.SetField("source_fid", int(feature.GetFID()))
        out_feature.SetField("length_m", length)
        out_feature.SetGeometry(boundary)
        target_layer.CreateFeature(out_feature)
        total_length += length
        count += 1

    target = None
    source = None
    return count, total_length


def spatial_reference_for(dataset: gdal.Dataset) -> osr.SpatialReference | None:
    projection = dataset.GetProjection()
    if not projection:
        return None
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromWkt(projection)
    return spatial_ref


def main() -> None:
    stats = compute(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
