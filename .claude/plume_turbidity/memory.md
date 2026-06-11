# Memory: Plume & Turbidity Mapping (WP4)

**Goal:** Detect sediment-rich meltwater plumes entering the coastal zone; produce turbidity maps using a Relative Turbidity Index (RTI) as a proxy for glacial melt discharge.

**Owner:** Ka-Wai Wong

---

## Current Status (PDR, 2026-06-11)

### ✅ Done
- Nothing specific to WP4 is implemented yet. The preprocessing infrastructure (clip, reproject, band access) is ready to support RTI development.

### ❌ Not yet done (needed by CDR 2026-07-02)
- **RTI formula definition** — literature review needed; candidate: ratio of red/NIR or blue/green for turbidity signal
- **RTI calculation module** — extend `indexes.py` with RTI alongside NDSI/NDWI
- **Plume spatial extent extraction** — thresholding RTI to binary plume mask (similar to glacier mask pipeline)
- **Temporal plume maps** — seasonal/annual comparison of plume occurrence and extent

---

## Scientific Background

Glacial meltwater carries suspended sediment, making it optically darker/brighter in specific bands. Common approaches:
- **RTI (Relative Turbidity Index):** often `(Red − Blue) / (Red + Blue)` or band ratios tuned to local conditions
- **SPM (Suspended Particulate Matter):** empirical relationship with Rrs at red wavelengths
- Target: coastal zone seaward of glacier fronts, not the glacier surface itself

The RTI output feeds WP5 (biological correlation): plume extent/intensity is correlated with chlorophyll-a from Copernicus Marine data.

---

## Key Constraints

- Plume signal is in coastal/marine pixels — must use scenes with sufficient ocean coverage within AOI
- Atmospheric correction quality matters more for water-leaving reflectance (L2A already corrected for S2)
- Landsat also provides usable coastal bands; sensor cross-calibration needed for time series

---

## Next Steps (toward CDR 2026-07-02)

1. Review literature for RTI formula best suited to glacial fjord environment
2. Add RTI to `glacier_app/indexes.py::BAND_ROLES` and `calculate_run_indexes()`
3. Add RTI threshold mask in `masks.py`
4. Produce test RTI maps for 2–3 summer scenes; visual QC against true-colour preview
5. Export plume extent as GeoJSON for WP5 correlation analysis

---

## File References

| File | Purpose |
|---|---|
| `glacier_app/indexes.py` | Add RTI formula here alongside NDSI/NDWI |
| `glacier_app/masks.py` | RTI threshold mask (same pipeline as NDSI/NDWI) |
| `glacier_app/config.py` | Add RTI default threshold constant |
