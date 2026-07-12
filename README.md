# Glacier Monitoring Workbench

A Tkinter desktop application for inspecting, filtering, and processing band-separated Sentinel-2 and Landsat satellite imagery of the southeast Vatnajokull glacier area (tile 28WDS, Iceland).

## What it does

| Stage | Action | Output |
|-------|--------|--------|
| **Browse** | Filter scenes by sensor, year, cloud cover; preview RGB and individual bands | — |
| **Preprocess** | Clip and reproject selected scenes to the study AOI (EPSG:32628) via GDAL | `preprocessed_manifest.csv` |
| **Indexes** | Calculate NDSI and NDWI rasters from preprocessed bands (numpy + GDAL) | `index_manifest.csv` |
| **Masks** | Threshold index rasters into binary glacier masks, report area in km² | `mask_manifest.csv` |
| **Boundaries** | Extract glacier boundary rasters plus polygon and boundary GeoJSON vectors from masks | `boundary_manifest.csv` |

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Conda** | Miniconda or Anaconda. [Download Miniconda](https://docs.conda.io/en/latest/miniconda.html) |
| **Git** | To clone the repository |
| **Sentinel-2 data** | Band-separated GeoTIFF files (see [Data layout](#data-layout) below) |

No QGIS installation is required — GDAL is installed via conda-forge.

---

## Setup (step by step)

### Step 1 — Clone the repository

```bash
git clone https://github.com/andywongkw0508-rgb/ESPACE_Project_GlacierMoni.git
cd ESPACE_Project_GlacierMoni
```

### Step 2 — Create the conda environment

```bash
conda env create -f Func/environment.yml
conda activate glacier-monitoring
```

This installs Python 3.11, GDAL (with Python bindings), NumPy, and Tkinter.

### Step 3 — Prepare your data directory

Your imagery must follow the layout below. The top-level folder can be anywhere on disk.

```
<DATA_ROOT>/
  sentinel/
    blue_B02/
      2025/
        2025-06-04_S2B_MSIL2A_20250604T125259_R138_T28WDS_20250604T181034_blue_B02.tif
        ...
    green_B03/
      2025/  ...
    red_B04/
      2025/  ...
    nir_B08/
      2025/  ...
    swir_B11/
      2025/  ...
    scene_classification_SCL/
      2025/  ...
    visual/
      2025/  ...
    preview/                        ← optional, RGB PNGs for quick preview
      2025/
        S2B_MSIL2A_..._preview.png
        ...
```

**Filename convention:**  
`YYYY-MM-DD_<Platform>_MSIL2A_<AcquisitionTime>_<Orbit>_<Tile>_<ProcessingTime>_<band>.tif`

### Step 4 — Create the `.env` file

Copy the example and fill in the path to your data root folder:

```bash
cp .env.example .env
```

Open `.env` and set `GLACIER_DATA_ROOT` to the absolute path of `<DATA_ROOT>` (the folder that **contains** the `sentinel/` subfolder):

```
# macOS / Linux
GLACIER_DATA_ROOT=/Users/yourname/data/vatnajokull

# Windows (use forward slashes or double backslashes)
GLACIER_DATA_ROOT=C:/Users/yourname/data/vatnajokull
```

> The `.env` file is loaded automatically on startup. You can also `export`/`set` the variable in your shell instead.

### Step 5 — Generate the scene manifest

The app reads `master_manifest.csv` from `DATA_ROOT`. Generate it by scanning your downloaded TIF files:

```bash
python Func/generate_manifest.py
```

Expected output:

```
Written 18 scene(s) to /path/to/DATA_ROOT/master_manifest.csv
  2025-06-04  S2B_MSIL2A_20250604T125259_R138_T28WDS_20250604T181034  bands=7  preview
  ...
```

Re-run this script any time you add new scenes to the data directory.

### Step 6 — Launch the app

```bash
python app.py
```

The window opens showing all scenes from the manifest. Use the filters on the left to narrow by sensor, year, and cloud cover.

### Optional — Download sea-level data

The dashboard can be extended with sea surface height data from Copernicus Marine. The helper script downloads daily sea surface height above geoid (`zos`) for the project AOI and the project period.

```bash
conda env update -f Func/environment.yml
conda activate glacier-monitoring

# First run this to inspect the request
python Func/download_sea_level.py --dry-run

# Then download the NetCDF file
python Func/download_sea_level.py
```

Default request:

| Setting | Value |
|---|---|
| Product | Copernicus Marine Global Ocean Physics Reanalysis |
| Dataset | `cmems_mod_glo_phy_my_0.083deg_P1D-m` |
| Variable | `zos` |
| Period | `2017-01-01` to `2026-05-26` |
| Area | `config/aoi.json` bounding box |
| Output | `outputs/sea_level/vatnajokull_28wds_sea_level_zos_20170101_20260526.nc` |

The Copernicus Marine toolbox needs a free Copernicus Marine account. Either run `copernicusmarine login` once, or set `COPERNICUSMARINE_SERVICE_USERNAME` and `COPERNICUSMARINE_SERVICE_PASSWORD` in your shell before downloading. The output folder is ignored by Git because the NetCDF file is generated data.

Inside the desktop app, the top toolbar also has a `Sea Level` button. It opens a file picker for a Copernicus NetCDF file, generates a high-resolution sea-level PNG from the selected file, and updates the dashboard sea-level image panel.

If Windows reports that `gdal_netCDF.dll` is missing, update the environment with `conda env update -f Func/environment.yml`. The app reads Copernicus NetCDF files with `xarray`/`netCDF4` first, so the sea-level figure does not require the optional GDAL NetCDF plugin.

### Automatic sea and glacier surface temperature

The top-toolbar `Temperature Map` button creates a remote-sensing temperature map without asking for a temperature value. It matches the closest locally available Landsat 8/9 acquisition time to the active Sentinel-2 preview or processing result, streams that Landsat scene's Collection 2 Level-2 `ST_B10` asset from Microsoft Planetary Computer, and converts it to degrees Celsius.

The Celsius raster and color map contain only valid sea and glacier pixels. Land, cloud, and pixels outside the Landsat footprint remain NoData in the temperature GeoTIFF and appear only as uncolored RGB context in the map. Sea and glacier are separated automatically with the same-scene `QA_PIXEL`, NDWI, NDSI, and cloud masks. The map, Celsius GeoTIFF, class GeoTIFF, and processing metadata are saved under `outputs/results/surface_temperature/<year>/<scene_id>/` and displayed in the preview and dashboard. This action requires internet access to retrieve the signed Landsat thermal asset; the visible, near-infrared, shortwave-infrared, and QA bands must already exist in the configured data root.

The dashboard keeps the six-panel overview layout: chlorophyll-a, turbidity, and glacier boundary maps across the top, with numeric index metrics, sea level, and sea/glacier temperature below. The metric panel reports NDSI ice coverage, NDWI water coverage, NDTI distribution, median chlorophyll-a, and high-turbidity coverage for the selected scene. Every image panel supports `-`/`+` zoom, fit-to-panel, mouse-wheel zoom, and click-drag panning. Dashboard images are cached at a display-sized resolution so these interactions do not repeatedly load full-resolution PNGs.

The dashboard also includes a `Validation` tab. It discovers the latest boundary visual check, GLIMS reference summary, chlorophyll comparison reports, and turbidity comparison report under the existing output folders. The boundary card renders the project-generated outline in cyan and the historical GLIMS outline in magenta on the clean Sentinel-2 base image, with a dated legend. Each validation card shows the saved plot, key metrics, evidence type, and a concise interpretation; unfinished glacier accuracy metrics remain clearly labeled as visual-only validation.

Reference observations are never changed to improve agreement. Derived comparison layers may repair invalid geometry in memory, reproject, clip, resample, or apply a documented validity range so the products can be compared on a common grid. The raw GLIMS, Copernicus, HLS, and BBP source files remain unchanged, and the generated boundary overlay records its sources and processing in a JSON sidecar.

### Optional - Validate chlorophyll-a against reference points

Use `Func/validate_chlorophyll.py` to compare an app-generated `CHL_A.tif` with field or reference chlorophyll-a point measurements.

Input CSV example:

```csv
site_id,lon,lat,date,chlorophyll_a
sample_001,-16.42,64.06,2025-08-20,2.84
sample_002,-16.35,64.02,2025-08-20,3.12
```

Run:

```bash
python Func/validate_chlorophyll.py ^
  --raster outputs/preprocessed/<run>/indexes/<scene>/<scene>_CHL_A.tif ^
  --observations reference_chlorophyll_samples.csv ^
  --x-column lon ^
  --y-column lat ^
  --observed-column chlorophyll_a ^
  --observation-crs EPSG:4326 ^
  --window-size 3
```

The script samples the CHL-A raster at each point and reports bias, MAE, RMSE, R2, and Pearson correlation. Results are written to `outputs/results/chlorophyll_validation/`.

### HLS S30 30 m reference comparison

NASA HLS S30 can be used as a 30 m Sentinel-2-family comparison source. It is not an in-situ truth product; the helper script downloads NASA HLS S30 surface reflectance bands, derives a CHL-A proxy with the same OC4v4 blue/green equation used by the app, and then the validator compares the two rasters.

HLS S30 band downloads require a free NASA Earthdata Login. Add credentials to `.env`:

```bash
EARTHDATA_USERNAME=your_nasa_earthdata_username
EARTHDATA_PASSWORD=your_nasa_earthdata_password
```

Then run:

```bash
python Func/download_hls_s30_chlorophyll.py

python Func/validate_chlorophyll.py ^
  --raster outputs/results/indexes/CHL_A/2025/S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234_S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234_CHL_A.tif ^
  --reference-raster outputs/reference_chlorophyll/hls_s30/HLS.S30.T28WDS.2025232T124309.v2.0/HLS.S30.T28WDS.2025232T124309.v2.0_HLS_S30_CHL_A.tif ^
  --resampling average
```

Default HLS source: `HLS.S30.T28WDS.2025232T124309.v2.0`, DOI `10.5067/HLS/HLSS30.002`.

To create a separately labeled HLS calibration result after validation, run:

```bash
python Func/calibrate_chlorophyll.py
```

The calibration script keeps HLS reference values unchanged. It fits a quadratic log-space transformation to the app CHL-A values on 80% of deterministic spatial blocks and reports metrics only on the held-out 20%. The raw validation report remains available alongside the calibration report and plot.

The two Copernicus comparison cards can be regenerated with the same held-out-cell design:

```bash
python Func/calibrate_marine_validation.py
```

This creates separate Copernicus CHL-A and turbidity/BBP calibration reports and plots. Calibration is applied only to app values; Copernicus reference values and the original raw validation reports remain unchanged. The turbidity result is labeled provisional because monthly BBP is an indirect proxy and the held-out sample is small.

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `GLACIER_DATA_ROOT` | `../data/vatnajokull_28WDS_by_band` (sibling of repo) | Directory containing `master_manifest.csv` and the `sentinel/` subfolder |


Set `GLACIER_DATA_ROOT` in `.env` (loaded at startup) or export it in your shell before running `python app.py`.

---

## Processing workflow

```
master_manifest.csv
  └─ Browse & filter scenes
       └─ Add to basket
            └─ Run Preprocessing  →  outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/
                 └─ Calculate Indexes  →  .../indexes/<scene_id>/
                      └─ Build Mask  →  .../masks/<scene_id>/
                           └─ Extract Boundary  →  .../boundaries/<scene_id>/
```

### Preprocessing

- Clips to AOI (`config/aoi.json`, EPSG:4326 bounding box)
- Reprojects to EPSG:32628 (UTM zone 28N)
- Sentinel-2: choose 10 m / 20 m / 30 m in the UI; Landsat fixed at 30 m
- SCL and QA bands use nearest-neighbour resampling; spectral bands use bilinear
- Optional `Cloud mask` removes Sentinel-2 SCL no-data, defective, dark/shadow, cloud shadow, medium/high cloud, and cirrus pixels from analysis bands. Snow/ice is kept. For Landsat, QA fill, dilated cloud, cirrus, cloud, and cloud-shadow bits are removed.

### Index calculation

| Index | Formula |
|-------|---------|
| NDSI  | (Green − SWIR) / (Green + SWIR) |
| NDWI  | (Green − NIR) / (Green + NIR) |

### Mask builder

Default thresholds (editable in the UI):

| Index | Default threshold |
|-------|------------------|
| NDSI  | ≥ 0.40 |
| NDWI  | ≥ 0.20 |

Area statistics (pixel count, valid pixels, km²) are reported on-screen and saved to `mask_manifest.csv`.

For NDSI glacier masks, the mask builder also uses matching run outputs when available: `NDWI >= 0.20` pixels are removed as water, and Sentinel-2 SCL / Landsat QA Pixel removes cloud, shadow, water, and invalid pixels before boundary extraction.

### Boundary extraction

Select a mask in the `Processing Results` tab and click `Refined Boundary` to clean the mask and create a previewable boundary GeoTIFF, a polygon GeoJSON for the mask area, and a boundary-line GeoJSON for QGIS inspection or later retreat-distance measurements.

The refinement step removes small noisy patches, fills small holes, smooths the binary mask, and simplifies the polygon outline before extracting the boundary.

Boundary outputs are saved under `outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/boundaries/` and recorded in `boundary_manifest.csv` with boundary pixel count, polygon count, and boundary length.

### Organized result folders and overlays

Each run remains self-contained, but the app also copies key products into easier browsing folders:

```text
outputs/results/
  indexes/NDSI/<year>/
  indexes/NDWI/<year>/
  masks/<index>/<year>/
  boundaries/<year>/<scene_id>/
  overlays/
```

After loading processing results with one or more boundary results, click `Overlay Target`. The app uses `S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234` as the base image, creates a PNG in `outputs/results/overlays/` with boundaries colored by year, adds a year legend, and opens it in the preview window for visual inspection.

