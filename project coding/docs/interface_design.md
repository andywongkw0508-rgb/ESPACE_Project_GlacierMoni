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
- Preview panel for quick visual inspection.
- Image zoom controls for closer visual inspection.
- Drag-to-pan movement inside the preview canvas.
- Metadata panel for the selected scene.
- Band checker showing downloaded file availability and manifest URL availability.
- Band switching by selecting a band row; GeoTIFF bands are rendered into cached PNG previews.

## Current Modules

- Scene browser and filter table.
- Scene selection basket with CSV export.
- Interactive preview with zoom and pan.
- Band checker for selected scenes with preview switching.

## Basket Export

The basket exports to:

```text
outputs/selected_scenes.csv
```

The export includes scene metadata, preview path, and a JSON field containing matched downloaded band files.

## Later Screens

- QGIS preprocessing launcher.
- Index calculator for NDSI, NDWI, and NDVI.
- AI model preparation panel.
- Validation and map export panel.

## Design Direction

The app should feel like a practical scientific workbench:

- Dense enough for repeated data work.
- Clear filters and visible scene metadata.
- Minimal decoration.
- Strong separation between data selection, processing, and results.
