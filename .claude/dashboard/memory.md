# Memory: Dashboard & Reporting (WP6)

**Goal:** Build an interactive dashboard visualising glacier retreat, turbidity/plume dynamics, and biological response through maps, time-series plots, and comparison views. Final deliverable for Acceptance Review (AR, 2026-07-16).

**Owner:** Rahul Dada Sharmale

---

## Current Status (PDR, 2026-06-11)

### ✅ Done
- `glacier_app/result_exports.py` — basic CSV export helpers
- The Tkinter workbench provides interactive preview of individual outputs (not time-series)

### ❌ Not yet done (needed by AR 2026-07-16)
- Time-series chart: glacier area by year (NDSI mask areas across runs)
- Map view: multi-year boundary overlay (partially done via `overlays.py`, but not as dashboard)
- Plume/turbidity time series (depends on WP4 RTI completion)
- Biological correlation plot: RTI area vs. chlorophyll-a (depends on WP5 marine adapter)
- Export: publication-ready PNG figures + CSV tables
- Dashboard packaging: HTML viewer or standalone Python panel

---

## Requirements (SRD FR-14, FR-15, FR-16)

| Requirement | Description |
|---|---|
| FR-14 | Interactive dashboard: maps, temporal plots, comparison visualisations, metadata |
| FR-15 | Export: maps, figures, time series, tables as PNG/CSV |
| FR-16 | Reproducible workflow: scripts/notebooks |
| PR-09 | Dashboard visualisation response within 2 minutes |
| PR-10 | Dashboard outputs match processed analytics |

---

## Technology Options

| Option | Pros | Cons |
|---|---|---|
| **Panel/HoloViews** (Python) | Stays in conda env, interactive | Less portable than HTML |
| **Streamlit** | Fast to prototype, web-accessible | Extra dependency |
| **Static HTML + Folium/Leaflet** | No server, shareable | Interactive charts need JS |
| **Matplotlib + PDF report** | Simple, always works | Not interactive |

Recommended first target: **Matplotlib figures + PDF report** as guaranteed AR deliverable; optionally add Streamlit/Panel interactive view if time permits.

---

## Planned Dashboard Views

1. **Glacier Area Time Series** — annual NDSI mask area (km²) 2017–2026, Sentinel-2 + Landsat
2. **Boundary Map Panel** — multi-year glacier front overlay on 2026 true-colour base
3. **Turbidity/Plume Map** — RTI seasonal maps for 2–3 selected years (requires WP4)
4. **Biological Response Plot** — chlorophyll-a vs. plume area scatter / time series (requires WP5)
5. **Metadata Panel** — data sources, accuracy metrics, processing parameters

---

## Data Dependencies

| Dashboard View | Requires |
|---|---|
| Glacier area time series | `mask_manifest.csv` from multiple runs |
| Boundary map panel | Boundary GeoJSONs + base scene visual |
| Turbidity maps | RTI index output (WP4) |
| Bio correlation | Copernicus Marine + RTI colocation (WP5) |

---

## Next Steps (toward AR 2026-07-16)

1. Write `scripts/build_area_timeseries.py`: aggregate mask areas from all runs into one CSV
2. Write `scripts/plot_glacier_area.py`: matplotlib area-change chart
3. Write `scripts/build_boundary_map.py`: multi-year GeoJSON overlay figure
4. Once WP4/WP5 are ready: add turbidity and biological response panels
5. Package all outputs as PDF report + reproducible script set

---

## File References

| File | Purpose |
|---|---|
| `glacier_app/result_exports.py` | Existing export helpers |
| `glacier_app/overlays.py` | Year-coloured boundary overlay (extend for dashboard) |
| `outputs/preprocessed/*/mask_manifest.csv` | Source data for area time series |
| `outputs/preprocessed/*/boundaries/` | GeoJSON files for boundary map |
| `scripts/` | Dashboard build scripts (to create) |
