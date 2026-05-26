# Application Interface Design

## Purpose

The interface is a working control panel for the Vatnajokull 28WDS imagery collection. It should help us inspect scenes, filter the dataset, choose candidate images, and later launch processing steps.

Only this imagery source is in scope:

```text
C:\Users\USER\Documents\New project 3\data\vatnajokull_28WDS_by_band
```

## First Screen

The first interface is a three-column desktop layout:

```text
Filters and actions | Scene table | Preview and scene details
```

## Controls

- Sensor selector: all, Sentinel-2, Landsat.
- Year selector: all years or a single year.
- Max cloud filter.
- Search box for scene IDs.
- Scene table with date, sensor, cloud cover, platform, and tile/path.
- Scene selection basket for collecting scenes to process.
- Basket preprocessing action for clipping/reprojecting selected scenes.
- Sentinel-2 preprocessing resolution selector.
- Preprocessing run manager for reviewing and deleting one or more old output folders.
- Run-level index calculation action for NDSI and NDWI.
- Processing result browser for previewing output rasters.
- Preview panel for quick visual inspection.
- Image zoom controls for closer visual inspection.
- Drag-to-pan movement inside the preview canvas.
- Metadata panel for the selected scene.
- Band checker showing downloaded file availability and manifest URL availability.
- Band switching by selecting a band row; GeoTIFF bands are rendered into cached PNG previews.

## Current Modules

- Scene browser and filter table.
- Scene selection basket with CSV export.
- GDAL preprocessing launcher for selected basket scenes.
- NDSI and NDWI calculator for selected preprocessing run folders.
- Result preview tab for preprocessed bands and index rasters.
- Interactive preview with zoom and pan.
- Band checker for selected scenes with preview switching.

## Basket Export

The basket exports to:

```text
outputs/selected_scenes.csv
```

The export includes scene metadata, preview path, and a JSON field containing matched downloaded band files.

## Preprocessing Launcher

The preprocessing action reads the current basket selection directly, checks matched downloaded GeoTIFF bands, and writes clipped/reprojected rasters under:

```text
outputs/preprocessed/
```

It uses the AOI from `config/aoi.json` and a first-pass target CRS of `EPSG:32628`.

Sentinel-2 output resolution is selectable by the user: `10 m`, `20 m`, or `30 m`.

Landsat output resolution remains fixed at `30 m`.

Each run writes into its own folder:

```text
outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/
```

The app lists these run folders and lets the user multi-select old runs for deletion after confirmation.

## Index Calculator

The index calculator runs from selected preprocessing run folders and reads each run's `preprocessed_manifest.csv`.

It writes NDSI and NDWI rasters into:

```text
outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/indexes/
```

Each run receives an `index_manifest.csv` and `index_calculation.log`.

## Result Preview

The preview area includes a `Processing Results` tab. After the user selects one or more preprocessing runs and clicks `Load Results`, the app lists available output rasters from:

```text
preprocessed_manifest.csv
index_manifest.csv
```

Selecting a result row renders that GeoTIFF in the main preview window.

## Later Screens

- QGIS preprocessing launcher.
- NDVI and optional mask refinement.
- AI model preparation panel.
- Validation and map export panel.

## Design Direction

The app should feel like a practical scientific workbench:

- Dense enough for repeated data work.
- Clear filters and visible scene metadata.
- Minimal decoration.
- Strong separation between data selection, processing, and results.
