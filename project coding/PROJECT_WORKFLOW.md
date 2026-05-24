# Glacial Coastal Marine Programming Workflow

## Project Aim

Build a reproducible QGIS and Python workflow for studying southeast Vatnajokull glacial, coastal, and marine change using Sentinel-2 and Landsat imagery.

The first programming goal is not to train an AI model immediately. The first goal is to create a reliable geospatial pipeline, then add AI only where it improves mapping or automation.

## Working Area

- Programming folder: `C:\Users\USER\Documents\New project 3\project coding`
- Existing data root: `C:\Users\USER\Documents\New project 3\data`
- Main target area: southeast Vatnajokull / Sentinel-2 tile `28WDS`
- Approximate AOI: west `-17.65`, south `63.72`, east `-14.55`, north `64.70`

## Available Data

- Sentinel-2 Level-2A tile `28WDS`, 2017-2026
- Landsat Collection 2 Level-2 scenes intersecting the same southeast Vatnajokull area, 2000-2026
- Preview imagery for visual inspection
- Raw asset URLs for analysis bands

Important existing manifests:

- `data\vatnajokull_southeast_area_collection\focused_manifest.csv`
- `data\vatnajokull_28WDS_by_band\master_manifest.csv`
- `data\vatnajokull_28WDS_by_band\sentinel\visual\visual_manifest.csv`
- `data\vatnajokull_28WDS_by_band\landsat\preview\preview_manifest.csv`

## Toolchain

Use QGIS through its wrapper scripts:

```powershell
& "C:\Program Files\QGIS 4.0.2\bin\qgis_process-qgis.bat" --version
```

Use Python for data preparation, analysis, charts, and optional AI experiments. For PyQGIS scripts, use the QGIS Python environment with the required DLL and PROJ paths.

## Folder Structure

```text
project coding/
  config/       project settings, AOI definitions, model parameters
  docs/         workflow notes and method descriptions
  logs/         processing logs
  notebooks/    exploration notebooks
  outputs/      processed rasters, vectors, maps, tables, reports
  qgis/         QGIS project files, styles, processing models
  scripts/      Python and QGIS automation scripts
```

## Phase 1: Inventory And Setup

Objective: confirm the study area, source data, and software access.

Tasks:

- Confirm QGIS version and processing availability.
- Read existing manifests and count images by year, sensor, cloud cover, and band.
- Choose initial analysis years.
- Choose initial target outputs: glacier boundary, water/ocean mask, snow/ice mask, coastline, or change map.

Deliverables:

- Dataset inventory table.
- Selected scene list for a first test run.
- QGIS project file with AOI and preview layers.

## Phase 2: Data Selection

Objective: select clean, comparable imagery.

Recommended first dataset:

- Sentinel-2 Level-2A, tile `28WDS`
- Summer season only: June to September
- Lowest-cloud scenes per year
- Bands: green `B03`, red `B04`, NIR `B08`, SWIR `B11`, scene classification `SCL`, and visual preview

Tasks:

- Filter scenes by year, season, cloud cover, and available bands.
- Download only the required raw bands for selected scenes.
- Keep a reproducible CSV of every selected image.

Deliverables:

- `outputs/selected_scenes.csv`
- Downloaded working rasters, grouped by year and sensor.

## Phase 3: Preprocessing

Objective: make all imagery spatially consistent.

Tasks:

- Clip all rasters to the AOI.
- Reproject to one CRS.
- Align pixel size and grid.
- Mask clouds, shadows, and invalid pixels using Sentinel `SCL` or Landsat `qa_pixel`.
- Create annual or seasonal composites where needed.

QGIS tools likely useful:

- `gdal:cliprasterbyextent`
- `gdal:warpreproject`
- `gdal:buildvirtualraster`
- `native:rastercalc`

Deliverables:

- Clean analysis rasters.
- Per-scene quality summary.
- Processing log.

## Phase 4: Baseline GIS Analysis

Objective: produce useful results before adding AI.

Recommended baseline indices:

- Snow/ice: `NDSI = (Green - SWIR) / (Green + SWIR)`
- Water: `NDWI = (Green - NIR) / (Green + NIR)`
- Vegetation/reference: `NDVI = (NIR - Red) / (NIR + Red)`

Tasks:

- Calculate NDSI, NDWI, and NDVI.
- Threshold indices into candidate classes.
- Clean masks with polygonization, dissolve, remove small objects, and smoothing.
- Extract glacier boundary and coast/water boundary.
- Calculate area by year.

Deliverables:

- Raster masks for ice/snow and water.
- Vector boundaries.
- Area-change table by year.
- First map outputs.

## Phase 5: Validation

Objective: check whether the outputs are trustworthy.

Tasks:

- Overlay masks on true-color previews in QGIS.
- Sample points manually for ice, water, land, cloud, and shadow.
- Compare automatic class labels to manual labels.
- Record confusion matrix, precision, recall, and overall accuracy.

Deliverables:

- Validation points layer.
- Accuracy table.
- Notes on failure cases such as cloud, shadow, debris-covered ice, and seasonal snow.

## Phase 6: AI Model Decision

Objective: decide whether AI adds value.

Use AI only if baseline index methods struggle with:

- Debris-covered glacier ice.
- Cloud/shadow confusion.
- Mixed coastline and glacier-front zones.
- Large manual correction workload.

Candidate AI approaches:

- Random Forest or XGBoost using spectral bands and indices.
- U-Net style segmentation for glacier/water masks if enough labeled pixels exist.
- Segment Anything style assisted labeling for faster mask creation, if available later.

Recommended first AI model:

- Start with Random Forest.
- Inputs: blue, green, red, NIR, SWIR, NDSI, NDWI, NDVI, elevation/slope if available.
- Labels: manually sampled QGIS points or polygons.
- Output: classified raster with classes such as ice, water, land, cloud/shadow, snow.

Deliverables:

- Training dataset.
- Baseline model script.
- Model accuracy report.
- Comparison against non-AI threshold method.

## Phase 7: Change Analysis

Objective: turn classifications into project findings.

Tasks:

- Compare annual glacier/water/coastline masks.
- Calculate glacier area change.
- Calculate water or proglacial lake area change if relevant.
- Measure retreat/advance along selected transects.
- Create map panels for selected years.

Deliverables:

- Change tables.
- Map series.
- Charts for area and boundary movement.

## Phase 8: Reporting And Dashboard

Objective: make results understandable and reusable.

Tasks:

- Export final maps from QGIS.
- Build a lightweight HTML or Python dashboard.
- Summarize methods, data sources, accuracy, and limitations.
- Keep scripts runnable from the project coding folder.

Deliverables:

- Final report figures.
- Dashboard or map viewer.
- Reproducible script list.

## First Programming Sprint

Start with a small vertical slice:

1. Read `focused_manifest.csv`.
2. Select 3-5 clean Sentinel-2 scenes from different years.
3. Download green, red, NIR, SWIR, SCL, and visual assets.
4. Clip them to the AOI.
5. Calculate NDSI and NDWI.
6. Produce first ice and water masks.
7. Open results in QGIS for visual checking.

Success criteria:

- One script runs end-to-end.
- At least one year produces a useful ice/water mask.
- Outputs are visible in QGIS.
- We know whether threshold GIS methods are enough or AI is justified.

## Suggested Script Order

```text
scripts/
  01_inventory.py
  02_select_scenes.py
  03_download_assets.py
  04_preprocess_qgis.py
  05_calculate_indices.py
  06_extract_masks.py
  07_validate_outputs.py
  08_train_ai_model.py
  09_change_analysis.py
  10_build_report_outputs.py
```

## Immediate Next Step

Create `01_inventory.py` to summarize the existing manifests and recommend the best scenes for the first test run.
