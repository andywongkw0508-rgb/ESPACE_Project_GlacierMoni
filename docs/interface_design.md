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
- Cloud-mask option for preprocessing, using Sentinel-2 SCL or Landsat QA Pixel where available.
- Sentinel-2 preprocessing resolution selector.
- Preprocessing run manager for reviewing and deleting one or more old output folders.
- Run-level index calculation action for NDSI and NDWI.
- Processing result browser for previewing output rasters.
- Mask builder controls for thresholding NDSI and NDWI outputs.
- Boundary extraction control for converting masks into preview rasters and GeoJSON vectors.
- Target-scene overlay control for year-colored visual comparison of extracted boundaries.
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
- Optional cloud/shadow masking during preprocessing.
- NDSI and NDWI calculator for selected preprocessing run folders.
- Result preview tab for preprocessed bands and index rasters.
- Threshold mask builder with area statistics.
- Boundary extractor with polygon and line-vector outputs.
- Organized results folder for indexes, masks, boundaries, and overlay PNGs.
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

The preprocessing controls include a `Cloud mask` checkbox. When enabled, Sentinel-2 SCL removes no-data, defective, dark/shadow, cloud shadow, medium/high cloud, and cirrus pixels while keeping snow/ice. Landsat QA Pixel removes fill, dilated cloud, cirrus, cloud, and cloud-shadow pixels.

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
mask_manifest.csv
boundary_manifest.csv
```

Selecting a result row renders that GeoTIFF in the main preview window.

## Mask Builder

The `Processing Results` tab includes threshold controls for building binary masks from selected NDSI or NDWI rasters.

Default thresholds:

```text
NDSI >= 0.40
NDWI >= 0.20
```

Mask outputs are written into:

```text
outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/masks/
```

The app records each mask in `mask_manifest.csv` with pixel count and area in square kilometers.

For selected NDSI results, mask building automatically applies available exclusion rasters from the same run and scene: matching NDWI removes water pixels, while Sentinel-2 SCL or Landsat QA Pixel removes cloud, shadow, water, and invalid pixels.

## Boundary Extractor

The `Processing Results` tab includes a `Refined Boundary` action for selected mask rasters. It removes small noisy regions, fills small holes, smooths the mask, simplifies the polygon, and then extracts the boundary.

Boundary outputs are written into:

```text
outputs/preprocessed/run_YYYYMMDD_HHMMSS_s2XXm/boundaries/
```

Each extraction creates:

- a boundary GeoTIFF for app preview,
- a polygon GeoJSON for the mask area,
- a boundary-line GeoJSON for QGIS and later retreat-distance measurements.

The app records each extraction in `boundary_manifest.csv` with boundary pixel count, polygon count, and boundary length in kilometers.

## Organized Result Folders

The run folders remain the source of truth, but the app also copies user-facing products into:

```text
outputs/results/
  indexes/NDSI/<year>/
  indexes/NDWI/<year>/
  masks/<index>/<year>/
  boundaries/<year>/<scene_id>/
  overlays/
```

## Boundary Overlay

The `Processing Results` tab includes an `Overlay Target` action. It uses `S2B_MSIL2A_20250820T124309_R095_T28WDS_20250820T162234` as the base image, preferring a loaded preprocessed visual raster and falling back to the raw visual GeoTIFF from the data root. Loaded boundary rasters are drawn with a different color for each year and the output includes a year/color legend.

The output PNG is saved to `outputs/results/overlays/` and shown in the preview window.

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
