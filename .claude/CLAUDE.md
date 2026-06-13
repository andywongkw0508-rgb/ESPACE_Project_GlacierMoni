# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Project title:** Glacial Meltwater Influences on Coastal Marine Systems: Dynamics, Water Quality and Environmental Changes
**Team:** Team Melwater — ESPACE Master's Programme, Technical University Munich (TUM)
**Customer:** Institute of Astronomical and Physical Geodesy, TUM

**Core research goal:** Connect glacier retreat (via satellite optical imagery) → meltwater plume dynamics → coastal marine biology (chlorophyll-a, primary productivity). The output is a reproducible processing workflow and interactive dashboard showing how cryosphere change drives marine ecosystem response.

**Study area:** Southeast Vatnajokull, Iceland — Sentinel-2 tile 28WDS
**AOI:** west −17.65, south 63.72, east −14.55, north 64.70 (EPSG:4326)

---

## Team Structure & Work Package Ownership

| Member | Role | Work Packages |
|---|---|---|
| Mehmet Sinan Güneri | Project Manager | WP1 Planning & Management |
| Sanjna Prakash | EO Application Lead | WP2 Data Acquisition |
| Maria-Cristina Munteanu | Data Engineer | WP2 Data Acquisition |
| Ka-Wai Wong | Software Engineer | WP3 Glacier Retreat, WP4 Plume Mapping |
| Jia-hao Liu (user) | Biological Impact Lead | WP3 Glacier Retreat, WP5 Biological Analysis |
| Rahul Dada Sharmale | Validation & Testing | WP6 Validation & Dashboard |

**Jia-hao Liu's primary responsibilities:**
- WP3: Glacier boundary delineation, retreat distance/area quantification, time-series products
- WP5: Statistical modelling of plume dynamics vs. primary productivity/chlorophyll-a

---

## Project Milestones (ECSS-style, Summer 2026)

| Date | Milestone | Status |
|---|---|---|
| 07.05.2026 | Project Plan Presentation (PP) | ✅ Done |
| 21.05.2026 | System Requirements Review (SRR) | ✅ Done |
| **11.06.2026** | **Preliminary Design Review (PDR)** | ✅ **Done (today)** |
| 02.07.2026 | Critical Design Review (CDR) | 🔲 Next |
| 16.07.2026 | Acceptance Review (AR) | 🔲 Pending |

---

## Implementation Status (as of PDR, 2026-06-11)

The desktop workbench implements the full GIS baseline pipeline (Phases 1–4 of the 8-phase workflow). Marine integration and temporal analysis remain planned.

### ✅ Implemented

| Feature | Where |
|---|---|
| Scene inventory (431 scenes: 180 S2, 251 Landsat, 2017–2026) | `data.py`, `generate_manifest.py` |
| Filtering (sensor, year, cloud %, scene ID search) | `app.py` — `apply_filters()` |
| Band availability checker & PNG preview generation | `bands.py` |
| Scene selection basket + CSV export | `app.py` — basket methods |
| Preprocessing: clip to AOI, reproject to EPSG:32628, grid-align | `preprocessing.py` — `gdal.Warp()` |
| NDSI = (Green − SWIR) / (Green + SWIR) | `indexes.py` |
| NDWI = (Green − NIR) / (Green + NIR) | `indexes.py` |
| Binary threshold masks + area statistics (km²) | `masks.py` |
| Refined glacier boundary extraction (raster + GeoJSON) | `boundaries.py`, `boundary_worker.py` |
| Year-coloured boundary overlay on target base scene | `overlays.py` |
| Results panel: load manifests, preview outputs, zoom/pan | `results.py`, `preview.py` |
| Run-folder manifest provenance (immutable, per-run CSVs) | all processing modules |

**PDR evidence:** 1 recorded run (`run_20260527_005032_s210m`); 35 preprocessed rasters, 10 index rasters, 2 mask rasters — all status=ok; 47 GeoTIFFs total.

### ❌ Not yet implemented (needed by CDR / AR)

| Feature | Target WP | Priority |
|---|---|---|
| Cloud/shadow masking integrated into preprocessing (SCL/QA_PIXEL) | WP3 | High — CDR |
| Scientific validation (confusion matrix, accuracy vs. reference) | WP6 | High — CDR |
| Temporal change metrics (year-over-year area diff, retreat distance) | WP3 | High — CDR |
| Relative Turbidity Index (RTI) for meltwater plume detection | WP4 | CDR |
| Copernicus Marine data ingestion (temperature, salinity, chl-a, NetCDF) | WP5 | CDR or reduced scope |
| Biological correlation analysis (plume vs. chlorophyll statistical model) | WP5 | CDR |
| Dashboard (interactive HTML or Python viewer) | WP6 | AR |
| Automated test suite | WP6 | AR |

---

## 8-Phase Scientific Workflow (PROJECT_WORKFLOW.md)

```
Phase 1 — Inventory & Setup        ✅ Done
Phase 2 — Data Selection            ✅ Done
Phase 3 — Preprocessing             ✅ Done
Phase 4 — Baseline GIS Analysis     ✅ Done (NDSI/NDWI/masks/boundaries)
Phase 5 — Validation                🔲 In progress (manual visual check only)
Phase 6 — AI Model Decision         🔲 Pending Phase 5 results
Phase 7 — Change Analysis           🔲 Planned (temporal metrics needed)
Phase 8 — Reporting & Dashboard     🔲 Planned (AR deliverable)
```

**AI decision:** Random Forest is the recommended first model if threshold methods prove insufficient for debris-covered ice, cloud/shadow confusion, or mixed glacier-front zones. Decision deferred until Phase 5 validation is complete.

---

## Key Scientific Parameters

| Parameter | Value |
|---|---|
| AOI | west −17.65, south 63.72, east −14.55, north 64.70 |
| Target CRS | EPSG:32628 (UTM Zone 28N) |
| Sentinel-2 resolution | 10 / 20 / 30 m (user-selectable) |
| Landsat resolution | Fixed 30 m |
| NDSI threshold | ≥ 0.40 (ice/snow candidate) |
| NDWI threshold | ≥ 0.20 (water candidate) |
| Sentinel-2 resampling | Bilinear (spectral), Nearest-neighbour (SCL) |
| Landsat resampling | Bilinear (spectral), Nearest-neighbour (QA_PIXEL) |
| Preferred season | June–September (summer melt window) |

---

## Environment Setup

```bash
conda env create -f environment.yml
conda activate glacier-monitoring
python app.py
```

The app expects the imagery dataset root to be set via `GLACIER_DATA_ROOT` (in `.env` or the shell environment). Set it to the directory that contains `master_manifest.csv` and the `sentinel/` subfolder. The only required environment variable is:

| Variable | Purpose |
|---|---|
| `GLACIER_DATA_ROOT` | Directory containing `master_manifest.csv` |

All GDAL operations use the `osgeo` Python bindings — no external binaries (`gdal_translate`, `gdalwarp`, `gdal_calc`) or QGIS are needed.

---

## Architecture

The app is a Tkinter desktop workbench (`glacier_app/app.py:ImageryApp`) for inspecting and processing satellite imagery. `app.py` at the project root is a thin entry-point that calls `glacier_app.app.main`.

**Data flow through the processing pipeline:**

```
master_manifest.csv
  └─ data.py::load_rows()           normalises rows, resolves preview paths
       └─ ImageryApp                 filter → basket → processing actions
            ├─ preprocessing.py     gdal.Warp() Python API → preprocessed_manifest.csv
            ├─ indexes.py           numpy + gdal Python API → index_manifest.csv
            ├─ masks.py             numpy + gdal Python API → mask_manifest.csv
            └─ boundaries.py        numpy + gdal Python API → boundary GeoJSON + raster
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
  boundaries/<scene_id>/
    <scene_id>_boundary.tif
    <scene_id>_boundary.geojson
    <scene_id>_polygons.geojson
```

**Module responsibilities:**

- `glacier_app/config.py` — all paths and band definitions for Sentinel-2 and Landsat; only `GLACIER_DATA_ROOT` is configurable
- `glacier_app/data.py` — reads `master_manifest.csv`; resolves `preview_file` paths relative to `PROJECT_ROOT` (parent of the repo)
- `glacier_app/bands.py` — checks which band GeoTIFFs exist on disk; generates PNG previews via `gdal.Translate()` Python API
- `glacier_app/preprocessing.py` — clips and reprojects band GeoTIFFs to AOI/CRS via `gdal.Warp()` Python API; bilinear resampling for spectral bands, nearest-neighbour for SCL/QA
- `glacier_app/indexes.py` — calculates NDSI and NDWI via numpy array math + `osgeo.gdal`; `BAND_ROLES` dict normalises Sentinel-2 vs Landsat band names to `green/nir/swir`
- `glacier_app/masks.py` — thresholds index rasters into binary masks and computes area statistics via numpy + `osgeo.gdal`
- `glacier_app/boundaries.py` + `boundary_worker.py` — extracts refined glacier boundary as raster + GeoJSON vector
- `glacier_app/overlays.py` — composites year-coloured boundary overlays onto a target base scene
- `glacier_app/preview.py` — zoom, pan, and fit logic for the Tkinter canvas
- `glacier_app/results.py` — aggregates outputs from manifests into a unified `ProcessingOutput` list for the Results tab
- `glacier_app/result_exports.py` — CSV/figure export helpers

**Threading model:** All GDAL operations (preprocessing, index calculation, mask building) run in daemon threads. Results are marshalled back to the Tkinter main thread via `self.after(0, callback, ...)`.

---

## Key Configuration

- AOI: `config/aoi.json` — bounding box `west=-17.65, south=63.72, east=-14.55, north=64.70` (EPSG:4326)
- Target CRS after preprocessing: `EPSG:32628`
- Sentinel-2 resolution: user-selectable 10/20/30 m; Landsat fixed at 30 m
- NDSI threshold default: `>= 0.40`; NDWI threshold default: `>= 0.20`
- Band preview PNGs are cached under `outputs/band_previews/`

---

## Collaboration Notes

- **Two active developers** (Ka-Wai Wong + Jia-hao Liu) editing the same repo; UI code causes most merge conflicts.
- `glacier_app/app.py` (1276 lines) is the highest-conflict file — a refactor to Mixin classes (one file per UI panel) has been discussed but not yet executed.
- Branch `develop` is the active integration branch; `codex/glacier-interface-workbench` is the main/base branch.

---

## External Data Sources (for future integration)

| Data | Source | Format | Status |
|---|---|---|---|
| Sentinel-2 L2A (B02/B03/B04/B08/B11/SCL) | Copernicus / local disk | GeoTIFF | ✅ Integrated |
| Landsat-8/9 Collection-2 L2 (blue/green/red/NIR/SWIR/QA) | USGS / local disk | GeoTIFF | ✅ Integrated |
| Ocean physics (temperature, salinity, currents) | Copernicus Marine Service | NetCDF | ❌ Planned |
| Biogeochemistry (chlorophyll-a, nutrients, productivity) | Copernicus Marine / PANGAEA | NetCDF/CSV | ❌ Planned |
| Glacier reference outlines | RGI / published studies | Shapefile/GeoJSON | ❌ Planned (for validation) |
