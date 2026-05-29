from __future__ import annotations

import json
import sys

import numpy as np
from osgeo import gdal


def main() -> None:
    gdal.UseExceptions()

    source_path = sys.argv[1]
    output_path = sys.argv[2]
    threshold = float(sys.argv[3])

    source = gdal.Open(source_path)
    if source is None:
        raise RuntimeError(f"Could not open source raster: {source_path}")

    band = source.GetRasterBand(1)
    array = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    valid = np.isfinite(array)
    if nodata is not None:
        valid &= array != nodata

    mask = (valid & (array >= threshold)).astype(np.uint8)

    driver = gdal.GetDriverByName("GTiff")
    target = driver.Create(
        output_path,
        source.RasterXSize,
        source.RasterYSize,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    if target is None:
        raise RuntimeError(f"Could not create mask raster: {output_path}")

    target.SetGeoTransform(source.GetGeoTransform())
    target.SetProjection(source.GetProjection())
    target.GetRasterBand(1).WriteArray(mask)
    target.FlushCache()

    geotransform = source.GetGeoTransform()
    pixel_area_m2 = abs(geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4])
    mask_pixels = int(mask.sum())
    valid_pixels = int(valid.sum())

    print(
        json.dumps(
            {
                "pixel_area_m2": pixel_area_m2,
                "mask_pixels": mask_pixels,
                "valid_pixels": valid_pixels,
                "area_m2": mask_pixels * pixel_area_m2,
                "area_km2": mask_pixels * pixel_area_m2 / 1_000_000,
            }
        )
    )


if __name__ == "__main__":
    main()
