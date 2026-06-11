# Memory: Glacier Analysis (WP3)

**Goal:** Delineate glacier boundaries over southeast Vatnajokull (tile 28WDS), quantify annual retreat distance and area change, produce time-series products covering 2017–2026.

**Owner:** Ka-Wai Wong & Jia-hao Liu

---

## Current Status (PDR, 2026-06-11)

### ✅ Done
- NDSI = (Green − SWIR) / (Green + SWIR), default threshold ≥ 0.40 → `indexes.py`
- NDWI = (Green − NIR) / (Green + NIR), default threshold ≥ 0.20 → `indexes.py`
- Binary threshold masks + pixel count + area (km²) → `masks.py`
- Refined glacier boundary raster + GeoJSON polygon → `boundaries.py` / `boundary_worker.py`
- Year-coloured boundary overlay on 2026 base scene → `overlays.py`
- Band-role normalisation (Sentinel-2 vs Landsat → `green/nir/swir`) → `indexes.py::BAND_ROLES`

### ❌ Not yet done (needed by CDR 2026-07-02)
- **Cloud/shadow masking** — SCL (Sentinel-2) and QA_PIXEL (Landsat) are preprocessed but not used to exclude invalid pixels before index calculation
- **Temporal change metrics** — no year-over-year area comparison; no retreat distance along transects
- **Scientific validation** — no confusion matrix; no reference labels; only visual overlay checks done so far

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| EPSG:32628 (UTM Zone 28N) as target CRS | Consistent metric units for area/distance measurement |
| Bilinear resampling for spectral bands | Preserves reflectance values; nearest-neighbour reserved for categorical SCL/QA |
| Per-run immutable manifest CSVs | Provenance: every output traceable to its input parameters |
| Boundary extraction uses morphological operations on binary mask | Avoids vectorisation artefacts from direct polygon conversion |

---

## Data

- **Sentinel-2:** B02/B03/B04/B08/B11 + SCL, 2017–2026, 10/20/30 m selectable
- **Landsat-8/9:** blue/green/red/NIR08/SWIR16 + QA_PIXEL, 2000–2026, fixed 30 m
- **AOI:** west −17.65, south 63.72, east −14.55, north 64.70 → EPSG:32628 after warp
- **Scene count:** 431 total (180 S2 + 251 Landsat)

---

## Next Steps (toward CDR 2026-07-02)

1. Integrate SCL/QA_PIXEL cloud masking into `preprocessing.py` or `masks.py` before index calc
2. Build `temporal_analysis.py`: load mask manifests across runs, compare areas by year, compute retreat metrics
3. Run validation: select 5–10 scenes with known-good summer imagery, overlay masks on visual preview, record confusion matrix
4. Output: area-change table (CSV) + boundary-movement map by year

---

## File References

| File | Purpose |
|---|---|
| `glacier_app/indexes.py` | NDSI / NDWI calculation, BAND_ROLES normalisation |
| `glacier_app/masks.py` | Binary mask + area stats |
| `glacier_app/boundaries.py` | Boundary raster + GeoJSON |
| `glacier_app/boundary_worker.py` | Threading wrapper for boundary extraction |
| `glacier_app/overlays.py` | Year-coloured boundary overlay |
| `outputs/preprocessed/run_*/index_manifest.csv` | Index output provenance |
| `outputs/preprocessed/run_*/mask_manifest.csv` | Mask output provenance |
