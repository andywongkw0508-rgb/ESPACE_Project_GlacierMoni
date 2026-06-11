# Memory: UI Workbench Development

**Goal:** Maintain and extend the Tkinter desktop workbench (`glacier_app/app.py`) — the primary interface for scene browsing, processing, and result review.

**Owner:** Ka-Wai Wong & Jia-hao Liu (shared)

---

## Current Status (PDR, 2026-06-11)

`glacier_app/app.py` is **1276 lines**, one monolithic `ImageryApp(tk.Tk)` class. All UI panels, event handlers, and business logic are co-located, causing frequent **merge conflicts** between the two developers.

### ✅ Implemented panels / features
- Left sidebar: sensor/year/cloud filters, scene count metric
- Centre panel: canvas preview (zoom/pan/fit), Band Checker tab, Results tab
- Right panel: Scene Inventory tree, Scene Selection Basket, Pipeline Runs tree
- Step bar (① Filter → ② Select → ③ Preprocess → ④ Analyse)
- Full processing integration: preprocessing → indexes → masks → boundary → overlay

### Pending architectural task
**Refactor `app.py` into Mixin classes** to eliminate merge conflicts:

```
glacier_app/
  app.py           (~50 lines)  — ImageryApp inherits all Mixins + main()
  theme.py         (~160 lines) — colours, fonts, configure_style()
  panel_filters.py (~130 lines) — left sidebar, apply_filters(), refresh_table()
  panel_preview.py (~250 lines) — canvas, step bar, band checker, results panel
  panel_workflow.py(~700 lines) — basket, preprocessing, runs, indexes, masks, boundaries
```

---

## Key Technical Constraints

- **Tkinter threading rule:** Never touch widgets from a non-main thread. All worker results returned via `self.after(0, callback, ...)`.
- **Widget references:** `self.tree`, `self.basket_tree`, `self.result_tree`, `self.runs_tree`, `self.preview_canvas`, `self.band_tree` — all accessed across methods; Mixin refactor must keep them on `self`.
- **Style system:** `ttk.Style` configured once in `configure_style()`; style names (`Sidebar.TButton`, `Accent.TButton`, etc.) used across all panels — must stay in `theme.py`.
- **No external GDAL binaries** — all GDAL via `osgeo` Python API.

---

## Colour Palette (do not change without team agreement)

```python
_C_SIDEBAR    = "#1e2d35"   # sidebar background
_C_ACCENT     = "#1e9ea8"   # teal accent
_C_APP_BG     = "#edf1f2"   # app background
_C_CARD       = "#ffffff"   # card background
_C_TEXT       = "#1f2d33"   # primary text
_C_MUTED      = "#617078"   # muted text
_C_BORDER     = "#d4dde1"   # light border
_C_DANGER     = "#c0392b"   # destructive action
```

---

## Collaboration Rule

- **Branch `develop`** is the active integration branch (both developers push here)
- Biggest conflict hotspot: `app.py` — the Mixin refactor would eliminate this
- Until the refactor is done: coordinate with Ka-Wai before editing `app.py` concurrently

---

## Next Steps

1. Execute Mixin refactor: extract `theme.py`, `panel_filters.py`, `panel_preview.py`, `panel_workflow.py`
2. When new processing features land (RTI, temporal metrics, marine adapter), wire them into the workflow panel
3. Add new tabs/panels as needed without expanding existing files

---

## File References

| File | Purpose |
|---|---|
| `glacier_app/app.py` | Main Tkinter app (currently monolithic — target for refactor) |
| `glacier_app/preview.py` | Canvas zoom/pan/fit controller |
| `glacier_app/result_exports.py` | CSV/figure export helpers |
| `glacier_app/config.py` | Sentinel/Landsat band definitions, all path constants |
