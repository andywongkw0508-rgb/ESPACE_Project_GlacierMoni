# Memory: Validation & Testing (WP6)

**Goal:** Verify that glacier masks, boundary extractions, and (later) plume/turbidity outputs meet scientific accuracy requirements. Produce a confusion matrix, accuracy metrics, and a repeatable test suite.

**Owner:** Rahul Dada Sharmale (primary); Ka-Wai Wong & Jia-hao Liu (scientific validation support)

---

## Current Status (PDR, 2026-06-11)

### ✅ Done
- Visual overlay checks only: masks overlaid on true-colour previews in the UI; no formal metrics yet.
- PDR evidence: 1 run with 47 GeoTIFFs, all status=ok — confirms pipeline runs end-to-end.

### ❌ Not yet done (needed by CDR 2026-07-02)
- Reference label collection (ice / water / land / cloud / shadow sample points)
- Confusion matrix, precision, recall, F1, overall accuracy
- Sentinel-2 vs. Landsat cross-sensor comparison for overlapping dates
- Automated test suite (unit + integration)

---

## Validation Plan

### Scientific Validation

1. **Select 5–10 scenes** with known-good summer imagery (low cloud, clear glacier front)
2. **Digitise reference points/polygons** in QGIS or QGIS-free alternative:
   - Classes: ice/snow, water, land, cloud, shadow, debris-covered ice
   - Minimum 50 points per class per scene
3. **Compare** automatic mask labels to reference labels
4. **Record metrics:**
   - Confusion matrix (per class)
   - Precision, Recall, F1-score
   - Overall accuracy
   - Kappa coefficient
5. **Document failure cases:** seasonal snow, debris-covered ice, cloud/shadow, mixed pixels at glacier front

### Technical Validation

| Test | Method | Status |
|---|---|---|
| Band-role mapping (S2 vs Landsat → green/nir/swir) | Unit test | ❌ pending |
| Threshold naming convention | Unit test | ❌ pending |
| Area calculation (pixel count × pixel area) | Unit test | ❌ pending |
| End-to-end preprocessing → mask pipeline | Integration test | ✅ observed (1 run) |
| Output file existence after each stage | Manifest status check | ✅ implemented |

---

## Accuracy Targets (SRD PR-06 / VVR-08)

- Glacier mapping accuracy: visual match to reference images and published RGI outlines
- Plume detection consistency: recurring structures across similar acquisitions
- No hard numeric thresholds set in SRD — "plausibility and comparison tests" (VVR-04)

---

## Next Steps (toward CDR 2026-07-02)

1. Write `tests/` directory with pytest unit tests for band-role mapping, area calculation, threshold naming
2. Create reference label dataset: 3–5 scenes × 50+ points per class
3. Write `scripts/validate_masks.py`: load reference labels, compare to mask rasters, output confusion matrix CSV
4. Run validation on existing `run_20260527_005032_s210m` outputs
5. Document failure cases

---

## File References

| File | Purpose |
|---|---|
| `glacier_app/indexes.py::BAND_ROLES` | Primary target for unit tests |
| `glacier_app/masks.py::build_mask()` | Area calculation to verify |
| `outputs/preprocessed/run_20260527_005032_s210m/` | First real run for integration validation |
| `tests/` | To create — pytest unit + integration tests |
| `scripts/validate_masks.py` | To create — accuracy assessment script |
