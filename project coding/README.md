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
