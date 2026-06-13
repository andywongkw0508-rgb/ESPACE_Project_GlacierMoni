from __future__ import annotations

import json
import sys

import numpy as np
from osgeo import gdal


def compute(
    source_path: str,
    output_path: str,
    threshold: float,
    water_path: str = "",
    water_threshold: float = 0.20,
    quality_path: str = "",
    sensor: str = "",
) -> dict[str, float | int]:
    gdal.UseExceptions()

    source = gdal.Open(source_path)
    if source is None:
        raise RuntimeError(f"Could not open source raster: {source_path}")

    band = source.GetRasterBand(1)
    array = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= array != nodata

    candidate = valid & (array >= threshold)
    water_excluded = np.zeros(candidate.shape, dtype=bool)
    cloud_excluded = np.zeros(candidate.shape, dtype=bool)

    if water_path:
        water_excluded = water_mask(water_path, source, water_threshold)
        candidate &= ~water_excluded

    if quality_path:
        cloud_excluded = quality_mask(quality_path, source, sensor)
        candidate &= ~cloud_excluded

    mask_arr = candidate.astype(np.uint8)

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
        raise RuntimeError(f"Could not create mask raster: {output_path}")

    target.SetGeoTransform(source.GetGeoTransform())
    target.SetProjection(source.GetProjection())
    target.GetRasterBand(1).WriteArray(mask_arr)
    target.FlushCache()

    geotransform = source.GetGeoTransform()
    pixel_area_m2 = abs(geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4])
    mask_pixels = int(mask_arr.sum())
    valid_pixels = int(valid.sum())
    water_excluded_pixels = int((water_excluded & valid).sum())
    cloud_excluded_pixels = int((cloud_excluded & valid).sum())

    return {
        "pixel_area_m2": pixel_area_m2,
        "mask_pixels": mask_pixels,
        "valid_pixels": valid_pixels,
        "water_excluded_pixels": water_excluded_pixels,
        "cloud_excluded_pixels": cloud_excluded_pixels,
        "excluded_pixels": int(((water_excluded | cloud_excluded) & valid).sum()),
        "area_m2": mask_pixels * pixel_area_m2,
        "area_km2": mask_pixels * pixel_area_m2 / 1_000_000,
    }


def water_mask(path: str, reference: gdal.Dataset, threshold: float) -> np.ndarray:
    ds = aligned_dataset(path, reference)
    band = ds.GetRasterBand(1)
    array = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= array != nodata
    return valid & (array >= threshold)


def quality_mask(path: str, reference: gdal.Dataset, sensor: str) -> np.ndarray:
    ds = aligned_dataset(path, reference)
    array = ds.GetRasterBand(1).ReadAsArray()
    if sensor == "sentinel-2-l2a":
        values = array.astype(np.uint8)
        # Remove no-data, defective, dark/shadow, cloud shadow, water,
        # medium/high cloud probability, and cirrus. Snow/ice is kept.
        invalid_classes = {0, 1, 2, 3, 6, 8, 9, 10}
        mask = np.zeros(values.shape, dtype=bool)
        for value in invalid_classes:
            mask |= values == value
        return mask
    if sensor == "landsat-c2-l2":
        values = array.astype(np.uint16)
        invalid_bits = [0, 1, 2, 3, 4]
        mask = np.zeros(values.shape, dtype=bool)
        for bit in invalid_bits:
            mask |= (values & (1 << bit)) != 0
        return mask
    return np.zeros(array.shape, dtype=bool)


def aligned_dataset(path: str, reference: gdal.Dataset) -> gdal.Dataset:
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Could not open exclusion raster: {path}")
    if same_grid(ds, reference):
        return ds

    gt = reference.GetGeoTransform()
    width = reference.RasterXSize
    height = reference.RasterYSize
    min_x = gt[0]
    max_y = gt[3]
    max_x = gt[0] + gt[1] * width + gt[2] * height
    min_y = gt[3] + gt[4] * width + gt[5] * height
    bounds = (min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))
    warped = gdal.Warp(
        "",
        ds,
        format="MEM",
        width=width,
        height=height,
        outputBounds=bounds,
        dstSRS=reference.GetProjection(),
        resampleAlg=gdal.GRA_NearestNeighbour,
    )
    if warped is None:
        raise RuntimeError(f"Could not align exclusion raster: {path}")
    return warped


def same_grid(left: gdal.Dataset, right: gdal.Dataset) -> bool:
    return (
        left.RasterXSize == right.RasterXSize
        and left.RasterYSize == right.RasterYSize
        and left.GetProjection() == right.GetProjection()
        and all(abs(a - b) < 1e-9 for a, b in zip(left.GetGeoTransform(), right.GetGeoTransform()))
    )


def main() -> None:
    stats = compute(
        sys.argv[1],
        sys.argv[2],
        float(sys.argv[3]),
        sys.argv[4] if len(sys.argv) > 4 else "",
        float(sys.argv[5]) if len(sys.argv) > 5 else 0.20,
        sys.argv[6] if len(sys.argv) > 6 else "",
        sys.argv[7] if len(sys.argv) > 7 else "",
    )
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
