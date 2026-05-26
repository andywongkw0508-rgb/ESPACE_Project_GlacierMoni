# Project Coding Workspace

This folder contains the programming workflow for the glacial coastal marine remote-sensing project.

Start here:

- `PROJECT_WORKFLOW.md` for the full project workflow.
- `config/aoi.json` for the initial southeast Vatnajokull study area settings.
- `scripts/` for Python and QGIS automation.
- `qgis/` for QGIS project files and styles.
- `outputs/` for generated rasters, vectors, tables, maps, and reports.

QGIS is available at:

```powershell
& "C:\Program Files\QGIS 4.0.2\bin\qgis_process-qgis.bat" --version
```

The recommended next script is:

```text
scripts/01_inventory.py
```

## Start The Interface

Run the first desktop interface with:

```powershell
& "C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\app.py
```

The interface uses only:

```text
C:\Users\USER\Documents\New project 3\data\vatnajokull_28WDS_by_band
```

Current interface features:

- Filter scenes by sensor, year, cloud cover, and scene ID.
- Add scenes to a selection basket for processing.
- Preview scenes with zoom and drag-to-pan movement.
- Check selected-scene band availability against downloaded GeoTIFF files and manifest URLs.
- Select a band row to switch the preview window to that band image.
- Export basket scenes to `outputs/selected_scenes.csv`.
- Run GDAL preprocessing for basket scenes, clipping them to the configured AOI and saving rasters under `outputs/preprocessed/`.
- Choose Sentinel-2 preprocessing resolution: `10 m`, `20 m`, or `30 m`; Landsat remains fixed at `30 m`.
- Manage preprocessing run folders from the app, including deleting one or more old runs.
- Calculate NDSI and NDWI rasters from selected preprocessing run folders.

## Code Layout

```text
app.py                  thin launcher
glacier_app/
  app.py                Tkinter application shell and UI callbacks
  bands.py              band availability checks and GeoTIFF preview rendering
  config.py             project paths and band definitions
  data.py               manifest loading and row normalization
  indexes.py            NDSI and NDWI calculation from preprocessed bands
  preprocessing.py      GDAL clipping/reprojection for basket scenes
  preview.py            zoom, fit, and pan behavior for the preview canvas
```

## Preprocessing

The `Run Preprocessing` button processes scenes currently in the basket.

Current first-pass settings:

- AOI: `config/aoi.json`
- Target CRS: `EPSG:32628`
- Sentinel-2 target resolution: user-selectable `10 m`, `20 m`, or `30 m`
- Landsat target resolution: fixed `30 m`
- Output folder: `outputs/preprocessed/`
- Each run folder: `outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/`
- Run manifest: `preprocessed_manifest.csv`
- Run log: `preprocess.log`
- One or more old run folders can be selected and deleted from the `Preprocessing Runs` manager in the app.

## Index Calculation

The `Calculate Indexes` button processes selected preprocessing run folders.

Current indexes:

- NDSI: `(Green - SWIR) / (Green + SWIR)`
- NDWI: `(Green - NIR) / (Green + NIR)`

Outputs are written under each run folder:

```text
outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/indexes/
```

Each run also receives:

- Index manifest: `index_manifest.csv`
- Index log: `index_calculation.log`
