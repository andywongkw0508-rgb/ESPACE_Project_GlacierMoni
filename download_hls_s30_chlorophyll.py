from __future__ import annotations

import argparse
import json
import math
import netrc
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests
from osgeo import gdal


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_APP_RASTER = (
    PROJECT_ROOT
    / "outputs"
    / "results"
    / "indexes"
    / "CHL_A"
    / "2025"
    / "S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234_S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234_CHL_A.tif"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reference_chlorophyll" / "hls_s30"
DEFAULT_GRANULE_ID = "HLS.S30.T28WDS.2025232T124309.v2.0"
CMR_GRANULE_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
HLS_SHORT_NAME = "HLSS30"
HLS_VERSION = "2.0"
HLS_DOI = "10.5067/HLS/HLSS30.002"
INDEX_NODATA = -9999.0
HLS_REFLECTANCE_SCALE = 0.0001
CHL_A_OC4V4_COEFFICIENTS = (0.366, -3.067, 1.930, 0.649, -1.532)
REQUIRED_BANDS = ("B02", "B03", "B08", "Fmask")


def main() -> int:
    load_env_file(PROJECT_ROOT / ".env")
    args = parse_args()
    output_dir = Path(args.output_dir).resolve() / args.granule_id
    output_dir.mkdir(parents=True, exist_ok=True)

    entry = find_hls_granule(args.granule_id)
    links = band_links(entry, REQUIRED_BANDS)
    write_granule_metadata(output_dir, entry, links)

    print(f"HLS S30 granule: {args.granule_id}")
    print(f"Time start: {entry.get('time_start', 'unknown')}")
    print(f"Output folder: {output_dir}")
    for band, url in links.items():
        print(f"{band}: {url}")

    if args.dry_run:
        print("\nDry run only. Add Earthdata credentials, then rerun without --dry-run to download.")
        return 0

    band_files: dict[str, Path] = {}
    if args.skip_download:
        for band in REQUIRED_BANDS:
            path = output_dir / f"{args.granule_id}.{band}.tif"
            if not path.exists():
                raise FileNotFoundError(f"--skip-download was used, but {path} is missing.")
            band_files[band] = path
    else:
        session = earthdata_session()
        if not earthdata_credentials_available():
            raise RuntimeError(
                "HLS S30 band files are protected by NASA Earthdata Login.\n"
                "Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD in .env or create a ~/.netrc entry for "
                "urs.earthdata.nasa.gov, then rerun this script."
            )
        for band, url in links.items():
            band_files[band] = download_band(session, url, output_dir, overwrite=args.overwrite)

    chlorophyll_file = output_dir / f"{args.granule_id}_HLS_S30_CHL_A.tif"
    process_hls_chlorophyll(band_files, chlorophyll_file)
    metadata_file = write_chlorophyll_metadata(output_dir, args.granule_id, entry, band_files, chlorophyll_file)

    print("\nCreated HLS-derived CHL-A reference:")
    print(chlorophyll_file)
    print(metadata_file)
    if args.app_raster:
        print("\nValidate against the app result with:")
        print(
            "python validate_chlorophyll.py "
            f"--raster \"{Path(args.app_raster)}\" "
            f"--reference-raster \"{chlorophyll_file}\" "
            "--resampling average"
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the matching NASA HLS S30 Sentinel-2 bands and derive a 30 m CHL-A "
            "comparison raster using the same OC4v4 blue/green polynomial as the app."
        )
    )
    parser.add_argument("--granule-id", default=DEFAULT_GRANULE_ID, help=f"Default: {DEFAULT_GRANULE_ID}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"Default: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--app-raster", default=str(DEFAULT_APP_RASTER), help="App CHL-A raster used in the printed validation command.")
    parser.add_argument("--overwrite", action="store_true", help="Redownload band files even when local files exist.")
    parser.add_argument("--skip-download", action="store_true", help="Process already downloaded band files in the output folder.")
    parser.add_argument("--dry-run", action="store_true", help="Print the matched HLS band URLs without downloading.")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def find_hls_granule(granule_id: str) -> dict[str, Any]:
    response = requests.get(
        CMR_GRANULE_URL,
        params={
            "short_name": HLS_SHORT_NAME,
            "version": HLS_VERSION,
            "granule_ur": granule_id,
            "page_size": 1,
        },
        timeout=30,
    )
    response.raise_for_status()
    entries = response.json().get("feed", {}).get("entry", [])
    if not entries:
        raise RuntimeError(f"No NASA CMR HLS S30 granule was found for {granule_id}.")
    return entries[0]


def band_links(entry: dict[str, Any], bands: tuple[str, ...]) -> dict[str, str]:
    links: dict[str, str] = {}
    for link in entry.get("links", []):
        href = link.get("href", "")
        if not href.lower().startswith("https://") or not href.lower().endswith(".tif"):
            continue
        for band in bands:
            if href.endswith(f".{band}.tif"):
                links[band] = href
    missing = [band for band in bands if band not in links]
    if missing:
        raise RuntimeError(f"HLS granule is missing required band link(s): {', '.join(missing)}")
    return links


def write_granule_metadata(output_dir: Path, entry: dict[str, Any], links: dict[str, str]) -> None:
    metadata = {
        "source": "NASA HLS Sentinel-2 MSI Surface Reflectance Daily Global 30m v2.0",
        "short_name": HLS_SHORT_NAME,
        "version": HLS_VERSION,
        "doi": HLS_DOI,
        "granule_id": entry.get("title") or entry.get("producer_granule_id"),
        "time_start": entry.get("time_start"),
        "time_end": entry.get("time_end"),
        "band_links": links,
    }
    (output_dir / "hls_s30_granule_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def earthdata_credentials_available() -> bool:
    username = os.environ.get("EARTHDATA_USERNAME") or os.environ.get("NASA_EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD") or os.environ.get("NASA_EARTHDATA_PASSWORD")
    if username and password:
        return True
    try:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
    except (FileNotFoundError, netrc.NetrcParseError):
        return False
    return auth is not None


def earthdata_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "ESPACE-GlacierMoni-HLS-validation/1.0"})
    username = os.environ.get("EARTHDATA_USERNAME") or os.environ.get("NASA_EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD") or os.environ.get("NASA_EARTHDATA_PASSWORD")
    if username and password:
        session.auth = (username, password)
    return session


def download_band(session: requests.Session, url: str, output_dir: Path, overwrite: bool = False) -> Path:
    output_file = output_dir / Path(url).name
    if output_file.exists() and output_file.stat().st_size > 0 and not overwrite:
        print(f"Using existing {output_file.name}")
        return output_file

    print(f"Downloading {output_file.name}")
    authorize_earthdata_redirect(session, url)
    response = session.get(url, stream=True, allow_redirects=True, timeout=120)
    if response.status_code in {401, 403} or "urs.earthdata.nasa.gov" in response.url:
        raise RuntimeError(
            "NASA Earthdata authentication failed while downloading HLS S30. "
            "Check EARTHDATA_USERNAME/EARTHDATA_PASSWORD or ~/.netrc."
        )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type.lower():
        raise RuntimeError(
            f"Expected a GeoTIFF but received HTML from {response.url}. "
            "This usually means Earthdata authentication did not complete."
        )

    temporary_file = output_file.with_suffix(output_file.suffix + ".part")
    with temporary_file.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    temporary_file.replace(output_file)
    return output_file


def authorize_earthdata_redirect(session: requests.Session, url: str) -> None:
    response = session.get(url, stream=True, allow_redirects=False, timeout=60)
    response.close()
    location = response.headers.get("Location", "")
    if response.status_code in {301, 302, 303, 307, 308} and "urs.earthdata.nasa.gov" in location:
        login_response = session.get(location, allow_redirects=True, timeout=120)
        if login_response.status_code in {401, 403}:
            raise RuntimeError(
                "NASA Earthdata authentication was rejected. Check EARTHDATA_USERNAME/EARTHDATA_PASSWORD."
            )
        login_response.close()


def process_hls_chlorophyll(band_files: dict[str, Path], output_file: Path) -> None:
    blue, invalid_blue, reference_ds = read_reflectance(band_files["B02"])
    green, invalid_green, _green_ds = read_reflectance(band_files["B03"])
    nir, invalid_nir, _nir_ds = read_reflectance(band_files["B08"])
    fmask, invalid_fmask = read_fmask(band_files["Fmask"])

    invalid = invalid_blue | invalid_green | invalid_nir | invalid_fmask
    water_mask = hls_fmask_water(fmask) & ~invalid
    if int(water_mask.sum()) < 10:
        water_mask = ndwi_water_mask(green, nir) & ~invalid

    chlorophyll = compute_chlorophyll_a(blue, green, invalid, water_mask)
    write_geotiff_like(output_file, reference_ds, chlorophyll)
    reference_ds = None


def read_reflectance(path: Path) -> tuple[np.ndarray, np.ndarray, Any]:
    dataset = gdal.Open(str(path))
    if dataset is None:
        raise RuntimeError(f"Could not open HLS band: {path}")
    band = dataset.GetRasterBand(1)
    values = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    invalid = ~np.isfinite(values)
    if nodata is not None:
        invalid |= np.isclose(values, float(nodata))
    reflectance = values * np.float32(HLS_REFLECTANCE_SCALE)
    return reflectance, invalid, dataset


def read_fmask(path: Path) -> tuple[np.ndarray, np.ndarray]:
    dataset = gdal.Open(str(path))
    if dataset is None:
        raise RuntimeError(f"Could not open HLS Fmask: {path}")
    band = dataset.GetRasterBand(1)
    values = band.ReadAsArray().astype(np.uint8)
    nodata = band.GetNoDataValue()
    invalid = np.zeros(values.shape, dtype=bool)
    if nodata is not None:
        invalid |= values == int(nodata)
    invalid |= values == 255
    dataset = None
    return values, invalid


def hls_fmask_water(fmask: np.ndarray) -> np.ndarray:
    cirrus = (fmask & (1 << 0)) != 0
    cloud = (fmask & (1 << 1)) != 0
    adjacent = (fmask & (1 << 2)) != 0
    shadow = (fmask & (1 << 3)) != 0
    snow_ice = (fmask & (1 << 4)) != 0
    water = (fmask & (1 << 5)) != 0
    return water & ~cirrus & ~cloud & ~adjacent & ~shadow & ~snow_ice


def ndwi_water_mask(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    denom = green + nir
    valid = np.isfinite(green) & np.isfinite(nir) & (denom != 0)
    ndwi = (green - nir) / np.where(valid, denom, np.float32(1.0))
    return valid & (ndwi >= np.float32(0.0))


def compute_chlorophyll_a(
    blue: np.ndarray,
    green: np.ndarray,
    invalid: np.ndarray,
    water_mask: np.ndarray,
) -> np.ndarray:
    invalid = invalid | (blue <= 0) | (green <= 0) | ~water_mask
    safe_blue = np.where(invalid, np.float32(1.0), blue)
    safe_green = np.where(invalid, np.float32(1.0), green)
    ratio = np.clip(safe_blue / safe_green, np.float32(0.01), np.float32(100.0))
    r = np.log10(ratio)
    a0, a1, a2, a3, a4 = (np.float32(value) for value in CHL_A_OC4V4_COEFFICIENTS)
    log_chla = a0 + a1 * r + a2 * r**2 + a3 * r**3 + a4 * r**4
    chlorophyll = np.power(np.float32(10.0), log_chla)
    chlorophyll = np.clip(chlorophyll, np.float32(0.0), np.float32(1000.0))
    return np.where(invalid, np.float32(INDEX_NODATA), chlorophyll).astype(np.float32)


def write_geotiff_like(output_file: Path, reference_ds: Any, array: np.ndarray) -> None:
    driver = gdal.GetDriverByName("GTiff")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    dataset = driver.Create(
        str(output_file),
        reference_ds.RasterXSize,
        reference_ds.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW", "PREDICTOR=3", "TILED=YES"],
    )
    if dataset is None:
        raise RuntimeError(f"Could not create output raster: {output_file}")
    dataset.SetGeoTransform(reference_ds.GetGeoTransform())
    dataset.SetProjection(reference_ds.GetProjection())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(INDEX_NODATA)
    band.SetDescription("HLS S30 derived CHL-A")
    band.WriteArray(array)
    dataset.FlushCache()
    dataset = None


def write_chlorophyll_metadata(
    output_dir: Path,
    granule_id: str,
    entry: dict[str, Any],
    band_files: dict[str, Path],
    chlorophyll_file: Path,
) -> Path:
    metadata_file = output_dir / f"{granule_id}_HLS_S30_CHL_A.json"
    metadata = {
        "source": "NASA HLS Sentinel-2 MSI Surface Reflectance Daily Global 30m v2.0",
        "source_url": "https://www.earthdata.nasa.gov/data/catalog/lpcloud-hlss30-2.0",
        "doi": HLS_DOI,
        "granule_id": granule_id,
        "time_start": entry.get("time_start"),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "OC4v4 blue/green polynomial applied to HLS S30 B02/B03 surface reflectance",
        "coefficients": CHL_A_OC4V4_COEFFICIENTS,
        "scale_factor_applied_to_reflectance_bands": HLS_REFLECTANCE_SCALE,
        "water_mask": "HLS Fmask water bit, excluding cirrus/cloud/adjacent/shadow/snow-ice; NDWI fallback if needed",
        "bands": {band: str(path.resolve()) for band, path in band_files.items()},
        "chlorophyll_file": str(chlorophyll_file.resolve()),
    }
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_file


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
