# Memory: Marine & Biological Impact Analysis (WP5)

**Goal:** Integrate Copernicus Marine Service variables (temperature, salinity, chlorophyll-a, nutrients) with optical EO indicators; statistically model the relationship between meltwater plume dynamics and primary productivity / biological response in the coastal marine zone.

**Owner:** Jia-hao Liu

---

## Current Status (PDR, 2026-06-11)

### ✅ Done
- Nothing in this WP is implemented yet. The project infrastructure (run folders, manifests) is ready to absorb marine data as an additional input.

### ❌ Not yet done (needed by CDR 2026-07-02 or agreed reduced scope)
- **Copernicus Marine data download** — identify products, write download/ingestion script
- **NetCDF adapter** — normalise marine variables to spatial/temporal grid compatible with EO scenes
- **Colocation logic** — match optical scene dates to nearest marine product timestamps
- **Correlation analysis** — statistical model linking RTI/NDWI plume metrics to chlorophyll-a
- **Biological response time series** — seasonal/interannual chlorophyll vs. melt season

---

## Copernicus Marine Data Targets

| Variable | Product | Resolution | Format |
|---|---|---|---|
| Sea surface temperature (SST) | CMEMS physics model/obs | ~5 km | NetCDF |
| Salinity | CMEMS physics model | ~5 km | NetCDF |
| Chlorophyll-a | CMEMS biogeochemistry | ~1–5 km | NetCDF |
| Nutrients (N, P) | CMEMS biogeochemistry | ~5 km | NetCDF |
| Ocean colour (Rrs) | CMEMS satellite obs | 300 m (Sentinel-3) | NetCDF |

Access: `marine.copernicus.eu` — requires free registration.
Python client: `copernicusmarine` package.

---

## Scientific Rationale

Chain of evidence:
1. Glacier retreat → increased meltwater discharge
2. Meltwater carries sediment → turbidity plumes (RTI signal in optical EO)
3. Plumes → stratification, light attenuation, nutrient input
4. → Changes in chlorophyll-a, primary productivity, zooplankton habitat
5. → Detectable in Copernicus Marine biogeochemistry products

Reference: Meltwater plumes affect zooplankton vertical distribution (Nature Scientific Reports, 2022).

---

## Key Constraints

- CDR scope: if Copernicus Marine integration cannot be demonstrated by 2026-07-02, agree with team to show the correlation analysis framework/design and defer full integration to AR
- Marine product spatial resolution (~5 km) is coarser than EO data (10–30 m) — spatial aggregation required
- Temporal alignment: match EO scene acquisition date to nearest marine product within ±7 days

---

## Planned Data Flow

```
Copernicus Marine API
  └─ marine_adapter.py::download_variables()   → NetCDF files
       └─ marine_adapter.py::to_dataframe()    → normalized CSV/array
            └─ correlation.py                  → statistical model
                 └─ outputs/marine/            → CSV tables, scatter plots
```

---

## Next Steps (toward CDR 2026-07-02)

1. Register on marine.copernicus.eu; identify exact product IDs for study area/period
2. Write `glacier_app/marine_adapter.py`: download + parse NetCDF, extract time series for AOI
3. Write colocation logic: for each glacier mask / RTI map, find matching marine observation
4. Prototype correlation plot: RTI plume area vs. chlorophyll-a concentration by month/year
5. Decide: full integration or present framework at CDR, complete at AR

---

## File References (planned)

| File | Purpose |
|---|---|
| `glacier_app/marine_adapter.py` | Copernicus Marine download + NetCDF normalisation (to create) |
| `glacier_app/correlation.py` | Plume–biology statistical analysis (to create) |
| `outputs/marine/` | Marine variable NetCDF + extracted CSV |
