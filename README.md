# Glacier Monitoring Workbench

A Tkinter desktop application for inspecting, filtering, and processing band-separated Sentinel-2 and Landsat satellite imagery of the southeast Vatnajokull glacier area (tile 28WDS, Iceland).

## What it does

| Stage | Action | Output |
|-------|--------|--------|
| **Browse** | Filter scenes by sensor, year, cloud cover; preview RGB and individual bands | — |
| **Preprocess** | Clip and reproject selected scenes to the study AOI (EPSG:32628) via GDAL | `preprocessed_manifest.csv` |
| **Indexes** | Calculate NDSI and NDWI rasters from preprocessed bands (numpy + GDAL) | `index_manifest.csv` |
| **Masks** | Threshold index rasters into binary glacier masks, report area in km² | `mask_manifest.csv` |

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
conda env create -f environment.yml
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
python generate_manifest.py
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
```

### Preprocessing

- Clips to AOI (`config/aoi.json`, EPSG:4326 bounding box)
- Reprojects to EPSG:32628 (UTM zone 28N)
- Sentinel-2: choose 10 m / 20 m / 30 m in the UI; Landsat fixed at 30 m
- SCL and QA bands use nearest-neighbour resampling; spectral bands use bilinear

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

