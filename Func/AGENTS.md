# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Environment Setup

```bash
conda env create -f Func/environment.yml
conda activate glacier-monitoring
python app.py
```

The app expects the imagery dataset root to be set via `GLACIER_DATA_ROOT` (in `.env` or the shell environment). Set it to the directory that contains `master_manifest.csv` and the `sentinel/` subfolder. The only required environment variable is:

| Variable | Purpose |
|---|---|
| `GLACIER_DATA_ROOT` | Directory containing `master_manifest.csv` |

All GDAL operations use the `osgeo` Python bindings — no external binaries (`gdal_translate`, `gdalwarp`, `gdal_calc`) or QGIS are needed.

## Architecture

The app is a Tkinter desktop workbench (`glacier_app/app.py:ImageryApp`) for inspecting and processing satellite imagery. `app.py` at the project root is a thin entry-point that calls `glacier_app.app.main`.

**Data flow through the processing pipeline:**

```
master_manifest.csv
  └─ data.py::load_rows()           normalises rows, resolves preview paths
       └─ ImageryApp                 filter → basket → processing actions
            ├─ preprocessing.py     gdal.Warp() Python API → preprocessed_manifest.csv
            ├─ indexes.py           numpy + gdal Python API → index_manifest.csv
            └─ masks.py             numpy + gdal Python API → mask_manifest.csv
```

Each stage writes its own manifest CSV inside the run folder so stages are independently queryable.

**Run folder structure** (under `outputs/preprocessed/`):

```
run_YYYYMMDD_HHMMSS_s2XXm/
  preprocessed_manifest.csv
  preprocess.log
  <scene_id>/
    <band>_preprocessed.tif
  indexes/<scene_id>/
    <scene_id>_NDSI.tif
    <scene_id>_NDWI.tif
  index_manifest.csv
  index_calculation.log
  masks/<scene_id>/
    <scene_id>_<index>_gte_<threshold>_mask.tif
  mask_manifest.csv
```

**Module responsibilities:**

- `glacier_app/config.py` — all paths and band definitions for Sentinel-2 and Landsat; only `GLACIER_DATA_ROOT` is configurable
- `glacier_app/data.py` — reads `master_manifest.csv`; resolves `preview_file` paths relative to `PROJECT_ROOT` (parent of the repo)
- `glacier_app/bands.py` — checks which band GeoTIFFs exist on disk; generates PNG previews via `gdal.Translate()` Python API
- `glacier_app/preprocessing.py` — clips and reprojects band GeoTIFFs to AOI/CRS via `gdal.Warp()` Python API; bilinear resampling for spectral bands, nearest-neighbour for SCL/QA
- `glacier_app/indexes.py` — calculates NDSI and NDWI via numpy array math + `osgeo.gdal`; `BAND_ROLES` dict normalises Sentinel-2 vs Landsat band names to `green/nir/swir`
- `glacier_app/masks.py` — thresholds index rasters into binary masks and computes area statistics via numpy + `osgeo.gdal`
- `glacier_app/preview.py` — zoom, pan, and fit logic for the Tkinter canvas
- `glacier_app/results.py` — aggregates outputs from both `preprocessed_manifest.csv` and `index_manifest.csv` into a unified `ProcessingOutput` list for the Results tab

**Threading model:** All GDAL operations (preprocessing, index calculation, mask building) run in daemon threads. Results are marshalled back to the Tkinter main thread via `self.after(0, callback, ...)`.

## Key Configuration

- AOI: `config/aoi.json` — bounding box `west=-17.65, south=63.72, east=-14.55, north=64.70` (EPSG:4326)
- Target CRS after preprocessing: `EPSG:32628`
- Sentinel-2 resolution: user-selectable 10/20/30 m; Landsat fixed at 30 m
- NDSI threshold default: `>= 0.40`; NDWI threshold default: `>= 0.20`
- Band preview PNGs are cached under `outputs/band_previews/`

## Project Context

This is Phase 1–4 of a multi-phase glacial monitoring workflow for southeast Vatnajokull (Sentinel-2 tile 28WDS) covering 2017–2026. The desktop app handles scene selection, preprocessing, index calculation, and mask building. Future phases will add AI-based classification (Random Forest or U-Net) once the baseline GIS pipeline is validated. See `PROJECT_WORKFLOW.md` for the full 8-phase plan.
