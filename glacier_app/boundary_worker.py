from __future__ import annotations

import json
import os
import sys

import numpy as np
from osgeo import gdal, ogr, osr


MIN_REGION_PIXELS = 1500
SMOOTHING_ITERATIONS = 2
SIMPLIFY_PIXELS = 0.5
POLYGONIZE_MAX_DIM = 5000  # retain near-native detail while bounding 10 m processing cost
DOMINANT_REGION_SHARE = 0.60
SECONDARY_REGION_RATIO = 0.10
FRAME_EXCLUSION_PIXELS = 3.0
LONG_STRAIGHT_EDGE_MIN_METERS = 5000.0


def compute(mask_path: str, boundary_raster_path: str, polygon_path: str, boundary_path: str) -> dict[str, float | int]:
    gdal.UseExceptions()
    ogr.UseExceptions()

    source = gdal.Open(mask_path)
    if source is None:
        raise RuntimeError(f"Could not open mask raster: {mask_path}")

    band = source.GetRasterBand(1)
    values = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    valid_mask = np.ones(values.shape, dtype=bool)
    if nodata is not None:
        valid_mask &= values != nodata
    original_mask = valid_mask & (values > 0)
    refined_mask = refine_mask(original_mask)
    refined_source = mask_dataset(source, refined_mask)
    region_stats = polygonize_mask(refined_source, polygon_path)
    selected_mask = rasterized_polygon_mask(source, polygon_path)
    if selected_mask.any():
        refined_mask = selected_mask

    boundary_count, length_m = write_boundary_vectors(polygon_path, boundary_path, source)
    boundary_count_pixels = write_boundary_raster(source, boundary_path, boundary_raster_path)

    return {
        "source_pixels": int(original_mask.sum()),
        "refined_pixels": int(refined_mask.sum()),
        "boundary_pixels": int(boundary_count_pixels),
        "polygon_count": int(region_stats["retained_region_count"]),
        "source_region_count": int(region_stats["source_region_count"]),
        "removed_region_count": int(region_stats["removed_region_count"]),
        "largest_region_share": float(region_stats["largest_region_share"]),
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


def write_boundary_raster(source: gdal.Dataset, boundary_path: str, output_path: str) -> int:
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
    out_band.Fill(0)

    vector = gdal.OpenEx(boundary_path, gdal.OF_VECTOR)
    if vector is None:
        raise RuntimeError(f"Could not open boundary vector: {boundary_path}")
    layer = vector.GetLayer(0)
    err = gdal.RasterizeLayer(target, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    if err != 0:
        raise RuntimeError(f"Could not rasterize boundary vector: {boundary_path}")

    boundary_pixels_count = int((out_band.ReadAsArray() > 0).sum())
    target.FlushCache()
    vector = None
    target = None
    return boundary_pixels_count


def _decimate_for_polygonize(source: gdal.Dataset) -> gdal.Dataset:
    """Return a decimated copy when the raster is too large for fast polygonization."""
    return decimate_dataset(source, POLYGONIZE_MAX_DIM)


def decimate_dataset(source: gdal.Dataset, maximum_dimension: int) -> gdal.Dataset:
    max_dim = max(source.RasterXSize, source.RasterYSize)
    if max_dim <= maximum_dimension:
        return source
    scale = maximum_dimension / max_dim
    w = max(1, int(source.RasterXSize * scale))
    h = max(1, int(source.RasterYSize * scale))
    ds = gdal.Warp("", source, format="MEM", width=w, height=h,
                   resampleAlg=gdal.GRA_NearestNeighbour)
    if ds is None:
        return source
    return ds


def polygonize_mask(source: gdal.Dataset, output_path: str) -> dict[str, float | int]:
    work = _decimate_for_polygonize(source)
    memory_driver = ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")
    if memory_driver is None:
        raise RuntimeError("OGR Memory driver is not available.")
    raw_datasource = memory_driver.CreateDataSource("")
    if raw_datasource is None:
        raise RuntimeError("Could not create temporary polygon layer.")

    spatial_ref = spatial_reference_for(source)
    raw_layer = raw_datasource.CreateLayer("raw_glacier_mask", spatial_ref, ogr.wkbPolygon)
    raw_layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    band = work.GetRasterBand(1)
    err = gdal.Polygonize(band, band, raw_layer, 0, [], callback=None)
    if err != 0:
        raise RuntimeError("GDAL polygonization failed while selecting glacier regions.")

    components: list[tuple[int, float, ogr.Geometry]] = []
    raw_layer.ResetReading()
    for index, feature in enumerate(raw_layer):
        geometry = feature.GetGeometryRef()
        if feature.GetField("value") != 1 or geometry is None or geometry.IsEmpty():
            continue
        components.append((index, float(geometry.GetArea()), geometry.Clone()))

    keep_fids, largest_share = selected_region_fids(
        [(component_id, area) for component_id, area, _geometry in components]
    )

    driver = ogr.GetDriverByName("GeoJSON")
    if driver is None:
        raise RuntimeError("GeoJSON driver is not available in GDAL/OGR.")
    if os.path.exists(output_path):
        driver.DeleteDataSource(output_path)
    datasource = driver.CreateDataSource(output_path)
    if datasource is None:
        raise RuntimeError(f"Could not create polygon output: {output_path}")

    layer = datasource.CreateLayer("glacier_mask", spatial_ref, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))

    kept = 0
    for component_id, _area, geometry in components:
        if component_id not in keep_fids:
            continue
        simplified = simplify_geometry(geometry, work)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("value", 1)
        feature.SetField("area_m2", float(simplified.GetArea()))
        feature.SetGeometry(simplified)
        layer.CreateFeature(feature)
        kept += 1

    datasource = None
    raw_datasource = None
    return {
        "source_region_count": len(components),
        "retained_region_count": kept,
        "removed_region_count": max(0, len(components) - kept),
        "largest_region_share": largest_share,
    }


def selected_region_fids(components: list[tuple[int, float]]) -> tuple[set[int], float]:
    if not components:
        return set(), 0.0

    ordered = sorted(components, key=lambda item: item[1], reverse=True)
    total_area = sum(max(0.0, area) for _fid, area in ordered)
    largest_fid, largest_area = ordered[0]
    largest_share = largest_area / total_area if total_area > 0 else 1.0
    if largest_share >= DOMINANT_REGION_SHARE:
        return {largest_fid}, largest_share

    minimum_area = largest_area * SECONDARY_REGION_RATIO
    selected = {fid for fid, area in ordered if area >= minimum_area}
    return selected or {largest_fid}, largest_share


def rasterized_polygon_mask(source: gdal.Dataset, polygon_path: str) -> np.ndarray:
    target = array_dataset(np.zeros((source.RasterYSize, source.RasterXSize), dtype=np.uint8))
    target.SetGeoTransform(source.GetGeoTransform())
    target.SetProjection(source.GetProjection())

    vector = gdal.OpenEx(polygon_path, gdal.OF_VECTOR)
    if vector is None:
        raise RuntimeError(f"Could not open selected glacier polygons: {polygon_path}")
    layer = vector.GetLayer(0)
    err = gdal.RasterizeLayer(target, [1], layer, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    if err != 0:
        raise RuntimeError(f"Could not rasterize selected glacier polygons: {polygon_path}")
    result = target.GetRasterBand(1).ReadAsArray().astype(bool)
    vector = None
    target = None
    return result


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


def write_boundary_vectors(
    polygon_path: str,
    output_path: str,
    raster_source: gdal.Dataset,
) -> tuple[int, float]:
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
    frame_exclusion = raster_frame_exclusion(raster_source)
    for feature in source_layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        boundary = exterior_boundary(geometry)
        if boundary is None or boundary.IsEmpty():
            continue
        if frame_exclusion is not None:
            boundary = boundary.Difference(frame_exclusion)
        boundary = remove_long_axis_aligned_segments(boundary, raster_source)
        if boundary is None or boundary.IsEmpty():
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


def exterior_boundary(geometry: ogr.Geometry) -> ogr.Geometry | None:
    name = geometry.GetGeometryName().upper()
    if name == "POLYGON":
        ring = geometry.GetGeometryRef(0)
        if ring is None:
            return None
        line = ogr.Geometry(ogr.wkbLineString)
        for index in range(ring.GetPointCount()):
            point = ring.GetPoint(index)
            line.AddPoint_2D(float(point[0]), float(point[1]))
        return line

    if name in {"MULTIPOLYGON", "GEOMETRYCOLLECTION"}:
        lines = ogr.Geometry(ogr.wkbMultiLineString)
        for index in range(geometry.GetGeometryCount()):
            child = exterior_boundary(geometry.GetGeometryRef(index))
            if child is None or child.IsEmpty():
                continue
            if child.GetGeometryName().upper() == "MULTILINESTRING":
                for child_index in range(child.GetGeometryCount()):
                    lines.AddGeometry(child.GetGeometryRef(child_index))
            else:
                lines.AddGeometry(child)
        return lines

    return geometry.Boundary()


def raster_frame_exclusion(dataset: gdal.Dataset) -> ogr.Geometry | None:
    distance = pixel_size(dataset) * FRAME_EXCLUSION_PIXELS
    if distance <= 0:
        return None

    geotransform = dataset.GetGeoTransform()
    corners = [
        map_pixel(geotransform, 0, 0),
        map_pixel(geotransform, dataset.RasterXSize, 0),
        map_pixel(geotransform, dataset.RasterXSize, dataset.RasterYSize),
        map_pixel(geotransform, 0, dataset.RasterYSize),
    ]
    frame = ogr.Geometry(ogr.wkbLineString)
    for x, y in corners + [corners[0]]:
        frame.AddPoint_2D(x, y)
    return frame.Buffer(distance)


def remove_long_axis_aligned_segments(
    geometry: ogr.Geometry | None,
    dataset: gdal.Dataset,
) -> ogr.Geometry | None:
    if geometry is None or geometry.IsEmpty():
        return geometry

    threshold = max(
        LONG_STRAIGHT_EDGE_MIN_METERS,
        pixel_size(dataset) * 150.0,
    )
    lines = split_line_geometry(geometry, threshold, pixel_size(dataset) * 1e-6)
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    combined = ogr.Geometry(ogr.wkbMultiLineString)
    for line in lines:
        combined.AddGeometry(line)
    return combined


def split_line_geometry(
    geometry: ogr.Geometry,
    threshold: float,
    tolerance: float,
) -> list[ogr.Geometry]:
    name = geometry.GetGeometryName().upper()
    if name in {"MULTILINESTRING", "GEOMETRYCOLLECTION"}:
        result: list[ogr.Geometry] = []
        for index in range(geometry.GetGeometryCount()):
            result.extend(split_line_geometry(geometry.GetGeometryRef(index), threshold, tolerance))
        return result
    if name not in {"LINESTRING", "LINEARRING"} or geometry.GetPointCount() < 2:
        return []

    result = []
    current: ogr.Geometry | None = None
    for index in range(geometry.GetPointCount() - 1):
        start = geometry.GetPoint(index)
        end = geometry.GetPoint(index + 1)
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        length = (dx * dx + dy * dy) ** 0.5
        artificial = length >= threshold and (abs(dx) <= tolerance or abs(dy) <= tolerance)
        if artificial:
            if current is not None and current.GetPointCount() >= 2:
                result.append(current)
            current = None
            continue

        if current is None:
            current = ogr.Geometry(ogr.wkbLineString)
            current.AddPoint_2D(float(start[0]), float(start[1]))
        current.AddPoint_2D(float(end[0]), float(end[1]))

    if current is not None and current.GetPointCount() >= 2:
        result.append(current)
    return result


def map_pixel(
    geotransform: tuple[float, float, float, float, float, float],
    pixel_x: int,
    pixel_y: int,
) -> tuple[float, float]:
    return (
        geotransform[0] + pixel_x * geotransform[1] + pixel_y * geotransform[2],
        geotransform[3] + pixel_x * geotransform[4] + pixel_y * geotransform[5],
    )


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
