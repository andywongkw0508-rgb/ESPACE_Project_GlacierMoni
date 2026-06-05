from __future__ import annotations

import csv
import json
import platform
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# ── platform-aware fonts ─────────────────────────────────────────────────────
_SYS = platform.system()
_UI_FONT  = "Helvetica Neue" if _SYS == "Darwin" else ("Segoe UI"          if _SYS == "Windows" else "DejaVu Sans")
_MONO_FONT = "Menlo"          if _SYS == "Darwin" else ("Consolas"          if _SYS == "Windows" else "DejaVu Sans Mono")

# ── colour palette ───────────────────────────────────────────────────────────
_C_SIDEBAR    = "#1e2d35"   # sidebar background
_C_SIDEBAR_H  = "#26404f"   # sidebar hover / button bg
_C_SIDEBAR_T  = "#cce0e8"   # sidebar text
_C_SIDEBAR_M  = "#728f9a"   # sidebar muted text
_C_SIDEBAR_BD = "#2c4252"   # sidebar separator / border
_C_SIDEBAR_F  = "#253c49"   # sidebar field background
_C_ACCENT     = "#1e9ea8"   # teal accent
_C_ACCENT_DK  = "#178590"   # teal accent — darker (hover / pressed)
_C_APP_BG     = "#edf1f2"   # app background
_C_CARD       = "#ffffff"   # card / panel background
_C_TEXT       = "#1f2d33"   # primary text
_C_MUTED      = "#617078"   # muted / secondary text
_C_BORDER     = "#d4dde1"   # light border
_C_DANGER     = "#c0392b"   # destructive action
_C_DANGER_DK  = "#a93226"
_C_TREE_ALT   = "#f4f8f9"   # alternating treeview row
_C_STATUS     = "#e3eaec"   # status bar background

from .bands import available_band_labels, band_preview_png, check_scene_bands
from .boundaries import BoundaryResult, extract_boundary
from .config import (
    APP_DIR,
    DATA_ROOT,
    DEFAULT_SENTINEL_PREPROCESS_RESOLUTION,
    DEFAULT_PREVIEW_SCENE_ID,
    MANIFEST,
    OVERLAY_BASE_SCENE_ID,
    SENTINEL_PREPROCESS_RESOLUTIONS,
)
from .data import load_rows
from .indexes import IndexResult, calculate_run_indexes
from .masks import MaskResult, build_mask, default_threshold_for
from .overlays import OverlayResult, best_2026_base, best_2026_base_from_rows, build_year_boundary_overlay
from .preprocessing import PreprocessResult, delete_preprocess_run, list_preprocess_runs, preprocess_rows
from .preview import PreviewController
from .results import ProcessingOutput, list_processing_outputs, processing_preview_png


class ImageryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Glacier Monitoring Workbench")
        self.geometry("1360x840")
        self.minsize(960, 780)

        self.rows = load_rows()
        self.filtered_rows: list[dict[str, str]] = []
        self.preview: PreviewController | None = None
        self.current_scene_row: dict[str, str] | None = None
        self.current_band_checks: list[dict[str, object]] = []
        self.current_processing_outputs: list[ProcessingOutput] = []
        self.loaded_processing_run_paths: list[Path] = []
        self.basket_rows: dict[str, dict[str, str]] = {}
        self.startup_preview_shown = False

        self.sensor_var = tk.StringVar(value="All sensors")
        self.year_var = tk.StringVar(value="All years")
        self.cloud_var = tk.DoubleVar(value=25.0)
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.sentinel_resolution_var = tk.StringVar(value=DEFAULT_SENTINEL_PREPROCESS_RESOLUTION)
        self.cloud_mask_var = tk.BooleanVar(value=True)
        self.mask_threshold_var = tk.StringVar(value="0.40")
        self.mask_stats_var = tk.StringVar(value="")

        self.configure_style()
        self.build_layout()
        self.apply_filters()

    def configure_style(self) -> None:
        self.configure(bg=_C_APP_BG)
        s = ttk.Style(self)
        s.theme_use("clam")

        # frames
        s.configure("TFrame",          background=_C_APP_BG)
        s.configure("Card.TFrame",      background=_C_CARD)
        s.configure("Sidebar.TFrame",   background=_C_SIDEBAR)

        # labels
        s.configure("TLabel",               background=_C_APP_BG,  foreground=_C_TEXT,       font=(_UI_FONT, 10))
        s.configure("Card.TLabel",          background=_C_CARD,    foreground=_C_TEXT,        font=(_UI_FONT, 10))
        s.configure("Card.Muted.TLabel",    background=_C_CARD,    foreground=_C_MUTED,       font=(_UI_FONT, 9))
        s.configure("AppTitle.TLabel",      background=_C_APP_BG,  foreground="#152328",      font=(_UI_FONT, 17, "bold"))
        s.configure("AppSub.TLabel",        background=_C_APP_BG,  foreground=_C_MUTED,       font=(_UI_FONT, 10))
        s.configure("Metric.TLabel",        background=_C_SIDEBAR, foreground=_C_ACCENT,      font=(_UI_FONT, 22, "bold"))
        s.configure("Sidebar.TLabel",       background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,   font=(_UI_FONT, 10))
        s.configure("Sidebar.Muted.TLabel", background=_C_SIDEBAR, foreground=_C_SIDEBAR_M,   font=(_UI_FONT, 9))
        s.configure("Sidebar.Bold.TLabel",  background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,   font=(_UI_FONT, 13, "bold"))
        s.configure("Sidebar.Sub.TLabel",   background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,   font=(_UI_FONT, 11, "bold"))
        s.configure("Status.TLabel",        background=_C_STATUS,  foreground=_C_MUTED,       font=(_UI_FONT, 9))

        # separators
        s.configure("TSeparator",         background=_C_BORDER)
        s.configure("Sidebar.TSeparator", background=_C_SIDEBAR_BD)

        # buttons — secondary (default)
        s.configure("TButton",
            font=(_UI_FONT, 10), padding=(10, 6),
            background="#dce5e8", foreground=_C_TEXT,
            bordercolor=_C_BORDER, darkcolor=_C_BORDER, lightcolor=_C_BORDER, relief="flat")
        s.map("TButton",
            background=[("active", "#c8d5da"), ("pressed", "#bccdd3"), ("disabled", "#e8eef0")],
            foreground=[("disabled", "#9badb5")],
            relief=[("active", "flat")])

        # buttons — primary accent
        s.configure("Accent.TButton",
            font=(_UI_FONT, 10, "bold"), padding=(12, 7),
            background=_C_ACCENT, foreground="white",
            bordercolor=_C_ACCENT, darkcolor=_C_ACCENT_DK, lightcolor=_C_ACCENT, relief="flat")
        s.map("Accent.TButton",
            background=[("active", _C_ACCENT_DK), ("pressed", _C_ACCENT_DK), ("disabled", "#8ec8cd")],
            foreground=[("disabled", "#d6edef")],
            relief=[("active", "flat")])

        # buttons — danger
        s.configure("Danger.TButton",
            font=(_UI_FONT, 10), padding=(10, 6),
            background=_C_CARD, foreground=_C_DANGER,
            bordercolor=_C_DANGER, darkcolor=_C_DANGER, lightcolor=_C_DANGER, relief="flat")
        s.map("Danger.TButton",
            background=[("active", "#fdf0ef"), ("pressed", "#fbe6e4")],
            foreground=[("active", _C_DANGER_DK)],
            relief=[("active", "flat")])

        # buttons — inside sidebar
        s.configure("Sidebar.TButton",
            font=(_UI_FONT, 9), padding=(8, 5),
            background=_C_SIDEBAR_H, foreground=_C_SIDEBAR_T,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD, relief="flat")
        s.map("Sidebar.TButton",
            background=[("active", "#2e4f62"), ("pressed", "#2e4f62")],
            relief=[("active", "flat")])

        s.configure("SidebarAccent.TButton",
            font=(_UI_FONT, 9, "bold"), padding=(8, 5),
            background=_C_ACCENT, foreground="white",
            bordercolor=_C_ACCENT, darkcolor=_C_ACCENT_DK, lightcolor=_C_ACCENT, relief="flat")
        s.map("SidebarAccent.TButton",
            background=[("active", _C_ACCENT_DK), ("pressed", _C_ACCENT_DK), ("disabled", "#2c6670")],
            foreground=[("disabled", "#9bc5ca")],
            relief=[("active", "flat")])

        # combobox
        s.configure("TCombobox",
            fieldbackground=_C_CARD, background=_C_CARD, foreground=_C_TEXT,
            selectbackground=_C_ACCENT, selectforeground="white", arrowcolor=_C_MUTED)
        s.map("TCombobox",
            fieldbackground=[("readonly", _C_CARD)],
            foreground=[("readonly", _C_TEXT)])

        s.configure("Sidebar.TCombobox",
            fieldbackground=_C_SIDEBAR_F, background=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T,
            selectbackground=_C_ACCENT, selectforeground="white", arrowcolor=_C_SIDEBAR_M,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)
        s.map("Sidebar.TCombobox",
            fieldbackground=[("readonly", _C_SIDEBAR_F)],
            foreground=[("readonly", _C_SIDEBAR_T)])

        # entry
        s.configure("Sidebar.TEntry",
            fieldbackground=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T,
            insertcolor=_C_SIDEBAR_T,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)

        # scale
        s.configure("Sidebar.Horizontal.TScale",
            background=_C_SIDEBAR, troughcolor=_C_SIDEBAR_F,
            darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)

        # notebook
        s.configure("TNotebook",     background=_C_CARD, bordercolor=_C_BORDER)
        s.configure("TNotebook.Tab", background="#e8eef0", foreground=_C_MUTED,
                    padding=(12, 5), font=(_UI_FONT, 9))
        s.map("TNotebook.Tab",
            background=[("selected", _C_CARD), ("active", "#f0f5f6")],
            foreground=[("selected", _C_TEXT)])

        # treeview — main content
        s.configure("Treeview",
            font=(_UI_FONT, 9), rowheight=26,
            background=_C_CARD, fieldbackground=_C_CARD, foreground=_C_TEXT)
        s.configure("Treeview.Heading",
            font=(_UI_FONT, 9, "bold"),
            background="#e8eef0", foreground=_C_TEXT,
            bordercolor=_C_BORDER, relief="flat")
        s.map("Treeview",
            background=[("selected", "#d6ecf0")],
            foreground=[("selected", "#0a3540")])

        # treeview — inside sidebar
        s.configure("Sidebar.Treeview",
            font=(_UI_FONT, 9), rowheight=22,
            background=_C_SIDEBAR_F, fieldbackground=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T)
        s.configure("Sidebar.Treeview.Heading",
            font=(_UI_FONT, 8, "bold"),
            background=_C_SIDEBAR, foreground=_C_SIDEBAR_M,
            bordercolor=_C_SIDEBAR_BD, relief="flat")
        s.map("Sidebar.Treeview",
            background=[("selected", _C_ACCENT)],
            foreground=[("selected", "white")])

    def build_layout(self) -> None:
        header = ttk.Frame(self, padding=(20, 14, 20, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Glacier Monitoring Workbench", style="AppTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Scene inspection and processing workbench for band-separated satellite imagery.",
            style="AppSub.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        ttk.Separator(self).pack(fill="x")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        self.build_filters(body)
        self.build_table(body)
        self.build_details(body)

        status_bar = ttk.Frame(self, style="TFrame")
        status_bar.pack(fill="x", side="bottom")
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w",
                  padding=(16, 5), style="Status.TLabel").pack(fill="x")

    def build_filters(self, parent: ttk.PanedWindow) -> None:
        panel = ttk.Frame(parent, style="Sidebar.TFrame", padding=(14, 16, 14, 16), width=244)
        panel.pack_propagate(False)
        parent.add(panel, weight=0)

        ttk.Label(panel, text="Filters", style="Sidebar.Bold.TLabel").pack(anchor="w")
        ttk.Label(
            panel,
            text="Browse and select scenes for processing.",
            style="Sidebar.Muted.TLabel",
            wraplength=212,
        ).pack(anchor="w", pady=(3, 14))

        years = ["All years"] + sorted({row["year"] for row in self.rows})
        sensors = ["All sensors"] + sorted({row["sensor"] for row in self.rows})

        self.add_combo(panel, "Sensor", self.sensor_var, sensors,
                       lbl_style="Sidebar.TLabel", combo_style="Sidebar.TCombobox")
        self.add_combo(panel, "Year", self.year_var, years,
                       lbl_style="Sidebar.TLabel", combo_style="Sidebar.TCombobox")

        ttk.Label(panel, text="Max cloud cover (%)", style="Sidebar.TLabel").pack(anchor="w", pady=(12, 4))
        cloud = ttk.Scale(
            panel, from_=0, to=100, variable=self.cloud_var,
            style="Sidebar.Horizontal.TScale",
            command=lambda _v: self.apply_filters(),
        )
        cloud.pack(fill="x")
        self.cloud_label = ttk.Label(panel, text="", style="Sidebar.Muted.TLabel")
        self.cloud_label.pack(anchor="w", pady=(3, 0))

        ttk.Label(panel, text="Search scene ID", style="Sidebar.TLabel").pack(anchor="w", pady=(12, 4))
        search = ttk.Entry(panel, textvariable=self.search_var, style="Sidebar.TEntry")
        search.pack(fill="x")
        search.bind("<KeyRelease>", lambda _event: self.apply_filters())

        ttk.Button(panel, text="Reset Filters", style="Sidebar.TButton",
                   command=self.reset_filters).pack(fill="x", pady=(14, 4))

        ttk.Separator(panel, style="Sidebar.TSeparator").pack(fill="x", pady=14)
        ttk.Label(panel, text="Dataset", style="Sidebar.Sub.TLabel").pack(anchor="w")
        ttk.Label(panel, text=str(DATA_ROOT), style="Sidebar.Muted.TLabel", wraplength=212).pack(
            anchor="w", pady=(4, 10)
        )

        self.metric_total = ttk.Label(panel, text="0", style="Metric.TLabel")
        self.metric_total.pack(anchor="w")
        ttk.Label(panel, text="matching scenes", style="Sidebar.Muted.TLabel").pack(anchor="w")

        self.build_run_manager(panel)

    def build_run_manager(self, parent: ttk.Frame) -> None:
        ttk.Separator(parent, style="Sidebar.TSeparator").pack(fill="x", pady=14)
        ttk.Label(parent, text="Preprocessing Runs", style="Sidebar.Sub.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="Select a run to calculate indexes, load results, or delete.",
            style="Sidebar.Muted.TLabel",
            wraplength=212,
        ).pack(anchor="w", pady=(3, 8))

        columns = ("run", "rasters", "modified")
        self.runs_tree = ttk.Treeview(
            parent, columns=columns, show="headings", height=3,
            style="Sidebar.Treeview", selectmode="extended",
        )
        for column, heading, width in (
            ("run",      "Run",      106),
            ("rasters",  "Files",     36),
            ("modified", "Modified",  76),
        ):
            self.runs_tree.heading(column, text=heading)
            self.runs_tree.column(column, width=width, anchor="w", stretch=column == "run")
        self.runs_tree.pack(fill="x")

        btn_frame = ttk.Frame(parent, style="Sidebar.TFrame")
        btn_frame.pack(fill="x", pady=(8, 0))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        ttk.Button(btn_frame, text="Refresh", style="Sidebar.TButton",
                   command=self.refresh_preprocess_runs).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ttk.Button(btn_frame, text="Delete", style="Sidebar.TButton",
                   command=self.delete_selected_preprocess_run).grid(row=0, column=1, sticky="ew", pady=(0, 4))

        self.index_button = ttk.Button(
            btn_frame, text="Calculate Indexes",
            style="SidebarAccent.TButton",
            command=self.calculate_selected_indexes,
        )
        self.index_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        ttk.Button(btn_frame, text="Load Results", style="Sidebar.TButton",
                   command=self.load_selected_processing_results).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )
        self.refresh_preprocess_runs()

    def build_table(self, parent: ttk.PanedWindow) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        parent.add(panel, weight=1)
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        table_header = ttk.Frame(panel, style="Card.TFrame")
        table_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        table_header.columnconfigure(0, weight=1)
        ttk.Label(table_header, text="Scene Inventory", style="Card.TLabel",
                  font=(_UI_FONT, 13, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(table_header, text="+ Add to Basket",
                   style="Accent.TButton",
                   command=self.add_selected_scene_to_basket).grid(row=0, column=1, sticky="e")

        columns = ("date", "sensor", "cloud", "platform", "tile")
        self.tree = ttk.Treeview(panel, columns=columns, show="headings", selectmode="browse")
        headings = {"date": "Date", "sensor": "Sensor", "cloud": "Cloud %",
                    "platform": "Platform", "tile": "Tile / Path"}
        widths = {"date": 110, "sensor": 110, "cloud": 74, "platform": 112, "tile": 100}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"sensor", "platform"})
        self.tree.tag_configure("odd", background=_C_TREE_ALT)

        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_scene_selected)
        self.tree.bind("<Double-1>", lambda _event: self.add_selected_scene_to_basket())

        self.build_basket(panel)

    def build_basket(self, parent: ttk.Frame) -> None:
        basket_panel = ttk.Frame(parent, style="Card.TFrame", padding=(0, 14, 0, 0))
        basket_panel.grid(row=2, column=0, columnspan=2, sticky="ew")
        basket_panel.columnconfigure(0, weight=1)

        bk_header = ttk.Frame(basket_panel, style="Card.TFrame")
        bk_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bk_header.columnconfigure(0, weight=1)
        self.basket_label = ttk.Label(
            bk_header, text="Scene Selection Basket (0)",
            style="Card.TLabel", font=(_UI_FONT, 12, "bold"),
        )
        self.basket_label.grid(row=0, column=0, sticky="w")

        # Controls row: resolution + remove/clear/export
        controls = ttk.Frame(basket_panel, style="Card.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(5, weight=1)
        ttk.Label(controls, text="Sentinel res. (m)", style="Card.Muted.TLabel").grid(row=0, column=0, padx=(0, 4))
        self.sentinel_resolution_combo = ttk.Combobox(
            controls,
            textvariable=self.sentinel_resolution_var,
            values=SENTINEL_PREPROCESS_RESOLUTIONS,
            state="readonly",
            width=4,
        )
        self.sentinel_resolution_combo.grid(row=0, column=1, padx=(0, 12))
        ttk.Checkbutton(
            controls,
            text="Cloud mask",
            variable=self.cloud_mask_var,
        ).grid(row=0, column=2, padx=(0, 12))
        ttk.Button(controls, text="Remove", command=self.remove_selected_basket_scene).grid(
            row=0, column=3, padx=(0, 4))
        ttk.Button(controls, text="Clear", command=self.clear_basket).grid(row=0, column=4, padx=(0, 4))
        ttk.Button(controls, text="Export CSV", command=self.export_basket_csv).grid(row=0, column=5, sticky="e")

        # Run Preprocessing — full-width accent button
        self.preprocess_button = ttk.Button(
            basket_panel, text="▶  Run Preprocessing",
            style="Accent.TButton",
            command=self.run_preprocessing,
        )
        self.preprocess_button.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        basket_columns = ("date", "sensor", "cloud", "item")
        self.basket_tree = ttk.Treeview(basket_panel, columns=basket_columns, show="headings",
                                        height=4, selectmode="browse")
        for column, heading, width in (
            ("date",   "Date",     90),
            ("sensor", "Sensor",  108),
            ("cloud",  "Cloud %",  70),
            ("item",   "Scene ID", 300),
        ):
            self.basket_tree.heading(column, text=heading)
            self.basket_tree.column(column, width=width, anchor="w", stretch=column == "item")
        self.basket_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.basket_tree.grid(row=3, column=0, sticky="ew")
        self.basket_tree.bind("<Double-1>", self.focus_basket_scene)

    def build_details(self, parent: ttk.PanedWindow) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        parent.add(panel, weight=1)
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="Preview", style="Card.TLabel",
                  font=(_UI_FONT, 13, "bold")).grid(row=0, column=0, sticky="w")

        viewer = ttk.Frame(panel, style="Card.TFrame")
        viewer.grid(row=1, column=0, sticky="nsew", pady=(10, 8))
        viewer.rowconfigure(0, weight=1)
        viewer.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            viewer, width=520, height=380,
            bg="#c6d9e0",
            highlightthickness=1, highlightbackground=_C_BORDER,
            cursor="fleur",
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        zoom_bar = ttk.Frame(panel, style="Card.TFrame")
        zoom_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        zoom_bar.columnconfigure(3, weight=1)
        ttk.Button(zoom_bar, text="−", width=3, command=lambda: self.preview.zoom_by(-1)).grid(
            row=0, column=0, padx=(0, 4))
        ttk.Button(zoom_bar, text="+", width=3, command=lambda: self.preview.zoom_by(1)).grid(
            row=0, column=1, padx=(0, 4))
        ttk.Button(zoom_bar, text="Fit", command=lambda: self.preview.fit()).grid(
            row=0, column=2, padx=(0, 10))
        self.zoom_label = ttk.Label(zoom_bar, text="100%", style="Card.Muted.TLabel")
        self.zoom_label.grid(row=0, column=3, sticky="w")

        self.preview = PreviewController(self.preview_canvas, self.zoom_label)
        self.preview_canvas.bind("<ButtonPress-1>", self.preview.start_pan)
        self.preview_canvas.bind("<B1-Motion>", self.preview.move_pan)
        self.preview_canvas.bind("<MouseWheel>", self.preview.mousewheel)
        self.preview_canvas.bind("<Button-4>", lambda event: self.preview.zoom_by(1))
        self.preview_canvas.bind("<Button-5>", lambda event: self.preview.zoom_by(-1))
        self.preview_canvas.bind("<Configure>", lambda _event: self.preview.center_if_needed())

        self.preview_tabs = ttk.Notebook(panel)
        self.preview_tabs.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        # Bands tab
        band_panel = ttk.Frame(self.preview_tabs, style="Card.TFrame", padding=8)
        self.preview_tabs.add(band_panel, text="  Bands  ")
        band_panel.columnconfigure(0, weight=1)
        ttk.Label(band_panel, text="Band Checker", style="Card.TLabel",
                  font=(_UI_FONT, 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(band_panel, text="Select a row to preview that band.",
                  style="Card.Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 6))

        band_columns = ("band", "disk", "manifest", "file")
        self.band_tree = ttk.Treeview(band_panel, columns=band_columns, show="headings",
                                      height=6, selectmode="browse")
        for column, heading, width in (
            ("band",     "Band",          86),
            ("disk",     "File",          60),
            ("manifest", "URL",           60),
            ("file",     "Matched file", 290),
        ):
            self.band_tree.heading(column, text=heading)
            self.band_tree.column(column, width=width, anchor="w", stretch=column == "file")
        self.band_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.band_tree.grid(row=2, column=0, sticky="ew")
        self.band_tree.bind("<<TreeviewSelect>>", self.on_band_selected)

        # Processing Results tab
        results_panel = ttk.Frame(self.preview_tabs, style="Card.TFrame", padding=8)
        self.preview_tabs.add(results_panel, text="  Results  ")
        results_panel.columnconfigure(0, weight=1)
        ttk.Label(results_panel, text="Processing Results", style="Card.TLabel",
                  font=(_UI_FONT, 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(results_panel, text="Select a row to preview that result.",
                  style="Card.Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 6))

        result_columns = ("run", "type", "result", "scene")
        self.result_tree = ttk.Treeview(results_panel, columns=result_columns, show="headings",
                                        height=6, selectmode="browse")
        for column, heading, width in (
            ("run",    "Run",      110),
            ("type",   "Type",      90),
            ("result", "Result",    124),
            ("scene",  "Scene ID", 275),
        ):
            self.result_tree.heading(column, text=heading)
            self.result_tree.column(column, width=width, anchor="w", stretch=column == "scene")
        self.result_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.result_tree.grid(row=2, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self.on_processing_result_selected)

        mask_bar = ttk.Frame(results_panel, style="Card.TFrame")
        mask_bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        mask_bar.columnconfigure(5, weight=1)
        ttk.Label(mask_bar, text="Threshold ≥", style="Card.Muted.TLabel").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(mask_bar, textvariable=self.mask_threshold_var, width=7).grid(row=0, column=1, padx=(0, 6))
        self.mask_button = ttk.Button(mask_bar, text="Build Mask",
                                      style="Accent.TButton", command=self.build_selected_mask)
        self.mask_button.grid(row=0, column=2, padx=(0, 10))
        self.boundary_button = ttk.Button(mask_bar, text="Refined Boundary",
                                          command=self.extract_selected_boundary)
        self.boundary_button.grid(row=0, column=3, padx=(0, 10))
        self.overlay_button = ttk.Button(mask_bar, text="Overlay Target",
                                         command=self.build_boundary_overlay)
        self.overlay_button.grid(row=0, column=4, padx=(0, 10))
        ttk.Label(mask_bar, textvariable=self.mask_stats_var, style="Card.Muted.TLabel").grid(
            row=0, column=5, sticky="w")

        self.detail_text = tk.Text(
            panel, height=8, wrap="word",
            borderwidth=1, relief="solid",
            bg="#f8fcfd", fg=_C_TEXT,
            font=(_MONO_FONT, 9),
            selectbackground=_C_ACCENT, selectforeground="white",
        )
        self.detail_text.grid(row=4, column=0, sticky="nsew")
        self.detail_text.configure(state="disabled")

        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Copy Scene ID",
                   command=self.copy_selected_scene_id).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Copy Preview Path",
                   command=self.copy_selected_preview_path).grid(row=0, column=1, sticky="ew")

    def add_combo(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        values: list[str],
        lbl_style: str = "TLabel",
        combo_style: str = "TCombobox",
    ) -> None:
        ttk.Label(parent, text=label, style=lbl_style).pack(anchor="w", pady=(8, 4))
        combo = ttk.Combobox(parent, textvariable=variable, values=values,
                             state="readonly", style=combo_style)
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_filters())

    def apply_filters(self) -> None:
        sensor = self.sensor_var.get()
        year = self.year_var.get()
        query = self.search_var.get().strip().lower()
        max_cloud = self.cloud_var.get()

        self.cloud_label.configure(text=f"{max_cloud:.0f}% or lower")
        filtered = []
        for row in self.rows:
            if sensor != "All sensors" and row["sensor"] != sensor:
                continue
            if year != "All years" and row["year"] != year:
                continue
            if row["cloud_value"] > max_cloud:
                continue
            if query and query not in row["item_id"].lower():
                continue
            filtered.append(row)

        filtered.sort(key=lambda item: (item["date"], item["sensor"], item["cloud_value"]))
        self.filtered_rows = filtered
        self.refresh_table()

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.filtered_rows):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("odd",) if index % 2 == 1 else (),
                values=(
                    row["date"],
                    row["sensor"],
                    f"{row['cloud_value']:.2f}",
                    row["platform"],
                    row["tile_or_path"],
                ),
            )
        self.metric_total.configure(text=str(len(self.filtered_rows)))
        self.status_var.set(f"Loaded {len(self.rows)} scenes from {MANIFEST.name}; showing {len(self.filtered_rows)}.")
        if self.filtered_rows:
            selected_index = self.default_startup_preview_index() if not self.startup_preview_shown else 0
            selected_item = self.tree.get_children()[selected_index]
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
            self.tree.see(selected_item)
            self.show_scene(self.filtered_rows[selected_index])
            self.startup_preview_shown = True
        else:
            self.preview.show_message("No scenes match the current filters.")
            self.clear_band_checker()
            self.show_details_text("No scene selected.")

    def default_startup_preview_index(self) -> int:
        candidates = [
            (index, row)
            for index, row in enumerate(self.filtered_rows)
            if row.get("item_id", "") == DEFAULT_PREVIEW_SCENE_ID and row.get("preview_path", "")
        ]
        if not candidates:
            return 0
        return candidates[0][0]

    def on_scene_selected(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.filtered_rows[int(selection[0])]
        self.show_scene(row)

    def show_scene(self, row: dict[str, str]) -> None:
        self.current_scene_row = row
        self.update_band_checker(row)
        self.preview.show_image(row.get("preview_path", ""), preserve_view=False)
        self.show_details_text(self.scene_details(row))

    def show_details_text(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def scene_details(self, row: dict[str, str]) -> str:
        fields = [
            ("Scene ID", row.get("item_id", "")),
            ("Date", row.get("date", "")),
            ("Sensor", row.get("sensor", "")),
            ("Platform", row.get("platform", "")),
            ("Tile / Path", row.get("tile_or_path", "")),
            ("Cloud cover", f"{row.get('cloud_value', 0.0):.2f}%"),
            ("Preview", row.get("preview_path", "")),
        ]

        available = available_band_labels(row)
        lines = [f"{label}: {value}" for label, value in fields]
        lines.append("")
        lines.append("Available raw assets:")
        lines.extend(f"- {band}" for band in available)
        return "\n".join(lines)

    def update_band_checker(self, row: dict[str, str]) -> None:
        self.clear_band_checker()
        checks = check_scene_bands(row)
        self.current_band_checks = checks
        disk_count = sum(1 for check in checks if check["disk_exists"])
        manifest_count = sum(1 for check in checks if check["manifest_url"])
        for index, check in enumerate(checks):
            self.band_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("odd",) if index % 2 == 1 else (),
                values=(
                    check["label"],
                    "Yes" if check["disk_exists"] else "No",
                    "Yes" if check["manifest_url"] else "No",
                    check["matched_file"],
                ),
            )
        self.status_var.set(
            f"Scene {row.get('item_id', '')}: {disk_count}/{len(checks)} band files found, "
            f"{manifest_count}/{len(checks)} raw URLs listed."
        )

    def clear_band_checker(self) -> None:
        self.band_tree.delete(*self.band_tree.get_children())
        self.current_band_checks = []

    def on_band_selected(self, _event: tk.Event) -> None:
        selection = self.band_tree.selection()
        if not selection:
            return
        check = self.current_band_checks[int(selection[0])]
        band_path = check.get("matched_path")
        if not band_path:
            self.status_var.set(f"No downloaded file is available for {check.get('label', 'this band')}.")
            return
        try:
            preview_path = band_preview_png(Path(str(band_path)), str(check.get("label", "band")))
        except RuntimeError as exc:
            self.status_var.set(str(exc))
            return
        self.preview.show_image(str(preview_path), preserve_view=True)
        self.status_var.set(f"Showing {check.get('label', 'band')} band preview.")

    def selected_row(self) -> dict[str, str] | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.filtered_rows[int(selection[0])]

    def add_selected_scene_to_basket(self) -> None:
        row = self.selected_row()
        if not row:
            self.status_var.set("Select a scene before adding it to the basket.")
            return
        item_id = row.get("item_id", "")
        if item_id in self.basket_rows:
            self.status_var.set("Scene is already in the basket.")
            return
        self.basket_rows[item_id] = row
        self.refresh_basket()
        self.status_var.set(f"Added scene to basket: {item_id}")

    def refresh_basket(self) -> None:
        self.basket_tree.delete(*self.basket_tree.get_children())
        rows = sorted(self.basket_rows.values(), key=lambda item: (item.get("date", ""), item.get("sensor", "")))
        for index, row in enumerate(rows):
            item_id = row.get("item_id", "")
            self.basket_tree.insert(
                "",
                "end",
                iid=item_id,
                tags=("odd",) if index % 2 == 1 else (),
                values=(
                    row.get("date", ""),
                    row.get("sensor", ""),
                    f"{row.get('cloud_value', 0.0):.2f}",
                    item_id,
                ),
            )
        self.basket_label.configure(text=f"Scene Selection Basket ({len(self.basket_rows)})")

    def remove_selected_basket_scene(self) -> None:
        selection = self.basket_tree.selection()
        if not selection:
            self.status_var.set("Select a basket scene to remove.")
            return
        item_id = selection[0]
        self.basket_rows.pop(item_id, None)
        self.refresh_basket()
        self.status_var.set(f"Removed scene from basket: {item_id}")

    def clear_basket(self) -> None:
        self.basket_rows.clear()
        self.refresh_basket()
        self.status_var.set("Scene basket cleared.")

    def focus_basket_scene(self, _event: tk.Event) -> None:
        selection = self.basket_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        for index, row in enumerate(self.filtered_rows):
            if row.get("item_id", "") == item_id:
                self.tree.selection_set(str(index))
                self.tree.focus(str(index))
                self.tree.see(str(index))
                self.show_scene(row)
                return
        row = self.basket_rows.get(item_id)
        if row:
            self.show_scene(row)
            self.status_var.set("Basket scene shown; current filters do not include it in the inventory table.")

    def export_basket_csv(self) -> None:
        if not self.basket_rows:
            self.status_var.set("Add scenes to the basket before exporting.")
            return
        default_dir = APP_DIR / "outputs"
        default_dir.mkdir(parents=True, exist_ok=True)
        selected_path = filedialog.asksaveasfilename(
            title="Save selected scenes CSV",
            initialdir=str(default_dir),
            initialfile="selected_scenes.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected_path:
            self.status_var.set("Basket export cancelled.")
            return
        output_path = Path(selected_path)
        export_fields = [
            "date",
            "sensor",
            "year",
            "item_id",
            "platform",
            "tile_or_path",
            "cloud_cover",
            "preview_path",
            "band_files_json",
        ]
        rows = sorted(self.basket_rows.values(), key=lambda item: (item.get("date", ""), item.get("sensor", "")))
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=export_fields)
            writer.writeheader()
            for row in rows:
                band_files = {
                    str(check["label"]): str(check["matched_path"])
                    for check in check_scene_bands(row)
                    if check.get("matched_path")
                }
                writer.writerow(
                    {
                        "date": row.get("date", ""),
                        "sensor": row.get("sensor", ""),
                        "year": row.get("year", ""),
                        "item_id": row.get("item_id", ""),
                        "platform": row.get("platform", ""),
                        "tile_or_path": row.get("tile_or_path", ""),
                        "cloud_cover": row.get("cloud_cover", ""),
                        "preview_path": row.get("preview_path", ""),
                        "band_files_json": json.dumps(band_files, ensure_ascii=True),
                    }
                )
        self.status_var.set(f"Exported {len(rows)} basket scenes to {output_path}")

    def run_preprocessing(self) -> None:
        if not self.basket_rows:
            self.status_var.set("Add scenes to the basket before preprocessing.")
            return
        rows = sorted(self.basket_rows.values(), key=lambda item: (item.get("date", ""), item.get("sensor", "")))
        sentinel_resolution = self.sentinel_resolution_var.get()
        cloud_mask = self.cloud_mask_var.get()
        self.preprocess_button.configure(state="disabled")
        self.status_var.set(
            f"Starting preprocessing for {len(rows)} scene(s). Sentinel: {sentinel_resolution} m; "
            f"Landsat: 30 m; cloud mask: {'on' if cloud_mask else 'off'}."
        )
        worker = threading.Thread(target=self.preprocess_worker, args=(rows, sentinel_resolution, cloud_mask), daemon=True)
        worker.start()

    def preprocess_worker(self, rows: list[dict[str, str]], sentinel_resolution: str, cloud_mask: bool) -> None:
        try:
            result = preprocess_rows(
                rows,
                sentinel_resolution=sentinel_resolution,
                cloud_mask=cloud_mask,
                progress=lambda message: self.after(0, self.status_var.set, message),
            )
        except Exception as exc:
            self.after(0, self.preprocess_finished, None, exc)
            return
        self.after(0, self.preprocess_finished, result, None)

    def preprocess_finished(self, result: PreprocessResult | None, error: Exception | None) -> None:
        self.preprocess_button.configure(state="normal")
        if error:
            self.status_var.set(f"Preprocessing failed: {error}")
            messagebox.showerror("Preprocessing failed", str(error))
            return
        if result is None:
            return
        self.status_var.set(
            f"Preprocessed {result.raster_count} raster(s) from {result.scene_count} scene(s). "
            f"Run folder: {result.run_dir}"
        )
        self.refresh_preprocess_runs()
        messagebox.showinfo(
            "Preprocessing complete",
            f"Rasters written: {result.raster_count}\n"
            f"Scenes processed: {result.scene_count}\n\n"
            f"Run folder:\n{result.run_dir}\n\n"
            f"Manifest:\n{result.output_manifest}\n\n"
            f"Log:\n{result.log_file}",
        )

    def refresh_preprocess_runs(self) -> None:
        if not hasattr(self, "runs_tree"):
            return
        self.runs_tree.delete(*self.runs_tree.get_children())
        for run in list_preprocess_runs():
            path = Path(run["path"])
            self.runs_tree.insert(
                "",
                "end",
                iid=str(path),
                values=(
                    run["name"],
                    run["raster_count"],
                    run["modified"],
                ),
            )

    def selected_preprocess_run_paths(self) -> list[Path]:
        return [Path(item_id) for item_id in self.runs_tree.selection()]

    def delete_selected_preprocess_run(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs to delete.")
            return
        if len(run_paths) == 1:
            prompt = f"This will permanently delete this output folder:\n\n{run_paths[0]}\n\nContinue?"
        else:
            listed_runs = "\n".join(f"- {path.name}" for path in run_paths[:10])
            remaining = len(run_paths) - 10
            if remaining > 0:
                listed_runs = f"{listed_runs}\n...and {remaining} more"
            prompt = (
                f"This will permanently delete {len(run_paths)} preprocessing output folders:\n\n"
                f"{listed_runs}\n\nContinue?"
            )
        confirmed = messagebox.askyesno(
            "Delete preprocessing runs?",
            prompt,
        )
        if not confirmed:
            self.status_var.set("Preprocessing run delete cancelled.")
            return
        deleted_runs = []
        failed_runs = []
        for run_path in run_paths:
            try:
                delete_preprocess_run(run_path)
            except Exception as exc:
                failed_runs.append((run_path, exc))
            else:
                deleted_runs.append(run_path)
        self.refresh_preprocess_runs()
        if failed_runs:
            details = "\n".join(f"{path.name}: {exc}" for path, exc in failed_runs)
            self.status_var.set(f"Deleted {len(deleted_runs)} run(s); {len(failed_runs)} failed.")
            messagebox.showerror("Delete failed", details)
            return
        self.clear_processing_results()
        if len(deleted_runs) == 1:
            self.status_var.set(f"Deleted preprocessing run: {deleted_runs[0].name}")
        else:
            self.status_var.set(f"Deleted {len(deleted_runs)} preprocessing runs.")

    def calculate_selected_indexes(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before calculating indexes.")
            return
        self.index_button.configure(state="disabled")
        self.status_var.set(f"Calculating NDSI and NDWI for {len(run_paths)} preprocessing run(s).")
        worker = threading.Thread(target=self.index_worker, args=(run_paths,), daemon=True)
        worker.start()

    def index_worker(self, run_paths: list[Path]) -> None:
        results = []
        failures = []
        for run_path in run_paths:
            try:
                result = calculate_run_indexes(
                    run_path,
                    progress=lambda message: self.after(0, self.status_var.set, message),
                )
            except Exception as exc:
                failures.append((run_path, exc))
            else:
                results.append(result)
        self.after(0, self.index_finished, results, failures)

    def index_finished(self, results: list[IndexResult], failures: list[tuple[Path, Exception]]) -> None:
        self.index_button.configure(state="normal")
        self.refresh_preprocess_runs()
        index_count = sum(result.index_count for result in results)
        scene_count = sum(result.scene_count for result in results)
        if failures:
            details = "\n".join(f"{path.name}: {exc}" for path, exc in failures)
            self.status_var.set(f"Created {index_count} index raster(s); {len(failures)} run(s) failed.")
            messagebox.showerror("Index calculation failed", details)
            return
        if not results:
            self.status_var.set("No indexes were calculated.")
            return
        manifest_lines = "\n".join(str(result.output_manifest) for result in results[:3])
        if len(results) > 3:
            manifest_lines = f"{manifest_lines}\n...and {len(results) - 3} more"
        self.status_var.set(f"Created {index_count} index raster(s) from {scene_count} scene(s).")
        self.load_processing_results_for_paths([result.run_dir for result in results])
        messagebox.showinfo(
            "Index calculation complete",
            f"Index rasters written: {index_count}\n"
            f"Scenes scanned: {scene_count}\n\n"
            f"Manifest file(s):\n{manifest_lines}",
        )

    def load_selected_processing_results(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before loading results.")
            return
        self.load_processing_results_for_paths(run_paths)

    def load_processing_results_for_paths(self, run_paths: list[Path], selected_output: Path | None = None) -> None:
        try:
            outputs = list_processing_outputs(run_paths)
        except Exception as exc:
            self.status_var.set(f"Could not load processing results: {exc}")
            messagebox.showerror("Load results failed", str(exc))
            return
        self.loaded_processing_run_paths = run_paths
        self.current_processing_outputs = outputs
        self.refresh_processing_results(selected_output)
        self.preview_tabs.select(1)
        if outputs:
            self.status_var.set(f"Loaded {len(outputs)} processing result raster(s).")
        else:
            self.status_var.set("No processing result rasters were found for the selected run(s).")

    def refresh_processing_results(self, selected_output: Path | None = None) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        selected_iid = ""
        for index, output in enumerate(self.current_processing_outputs):
            iid = str(index)
            self.result_tree.insert(
                "",
                "end",
                iid=iid,
                values=(output.run_name, output.kind, output.label, output.scene_id),
            )
            if selected_output and output.output_file.resolve() == selected_output.resolve():
                selected_iid = iid
        if selected_iid:
            self.result_tree.selection_set(selected_iid)
            self.result_tree.focus(selected_iid)
            self.result_tree.see(selected_iid)
            self.on_processing_result_selected(tk.Event())

    def clear_processing_results(self) -> None:
        self.current_processing_outputs = []
        self.loaded_processing_run_paths = []
        self.mask_stats_var.set("")
        if hasattr(self, "result_tree"):
            self.result_tree.delete(*self.result_tree.get_children())

    def selected_processing_output(self) -> ProcessingOutput | None:
        selection = self.result_tree.selection()
        if not selection:
            return None
        return self.current_processing_outputs[int(selection[0])]

    def on_processing_result_selected(self, _event: tk.Event) -> None:
        output = self.selected_processing_output()
        if output is None:
            return
        default_threshold = default_threshold_for(output)
        if default_threshold is not None:
            self.mask_threshold_var.set(f"{default_threshold:.2f}")
        try:
            preview_path = processing_preview_png(output)
        except RuntimeError as exc:
            self.status_var.set(str(exc))
            return
        self.preview.show_image(str(preview_path), preserve_view=True)
        self.show_details_text(self.processing_result_details(output))
        self.status_var.set(f"Showing {output.kind.lower()} result: {output.label}")

    def build_selected_mask(self) -> None:
        output = self.selected_processing_output()
        if output is None:
            self.status_var.set("Select an NDSI or NDWI result before building a mask.")
            return
        try:
            threshold = float(self.mask_threshold_var.get())
        except ValueError:
            self.status_var.set("Mask threshold must be a number.")
            return
        if threshold < -1 or threshold > 1:
            self.status_var.set("Mask threshold should be between -1 and 1.")
            return
        self.mask_button.configure(state="disabled")
        self.status_var.set(f"Building {output.label} mask with threshold >= {threshold:.3f}.")
        worker = threading.Thread(target=self.mask_worker, args=(output, threshold), daemon=True)
        worker.start()

    def extract_selected_boundary(self) -> None:
        output = self.selected_processing_output()
        if output is None or output.kind != "Mask":
            self.status_var.set("Select a mask result before extracting a boundary.")
            return
        self.boundary_button.configure(state="disabled")
        self.status_var.set(f"Extracting refined boundary from {output.label}.")
        worker = threading.Thread(target=self.boundary_worker, args=(output,), daemon=True)
        worker.start()

    def build_boundary_overlay(self) -> None:
        base = best_2026_base(self.current_processing_outputs) or best_2026_base_from_rows(self.rows)
        boundaries = [output for output in self.current_processing_outputs if output.kind == "Boundary"]
        if base is None:
            self.status_var.set(f"No target visual raster is available for overlay: {OVERLAY_BASE_SCENE_ID}")
            return
        if not boundaries:
            self.status_var.set("Extract at least one boundary before building the target-scene overlay.")
            return
        self.overlay_button.configure(state="disabled")
        self.status_var.set(f"Building year-colored overlay on target base: {base.label}.")
        worker = threading.Thread(target=self.overlay_worker, args=(base, boundaries), daemon=True)
        worker.start()

    def mask_worker(self, output: ProcessingOutput, threshold: float) -> None:
        try:
            result = build_mask(output, threshold)
        except Exception as exc:
            self.after(0, self.mask_finished, None, exc)
            return
        self.after(0, self.mask_finished, result, None)

    def boundary_worker(self, output: ProcessingOutput) -> None:
        try:
            result = extract_boundary(output)
        except Exception as exc:
            self.after(0, self.boundary_finished, None, exc)
            return
        self.after(0, self.boundary_finished, result, None)

    def overlay_worker(self, base: ProcessingOutput, boundaries: list[ProcessingOutput]) -> None:
        try:
            result = build_year_boundary_overlay(base, boundaries)
        except Exception as exc:
            self.after(0, self.overlay_finished, None, exc)
            return
        self.after(0, self.overlay_finished, result, None)

    def mask_finished(self, result: MaskResult | None, error: Exception | None) -> None:
        self.mask_button.configure(state="normal")
        if error:
            self.status_var.set(f"Mask failed: {error}")
            messagebox.showerror("Mask failed", str(error))
            return
        if result is None:
            return
        run_paths = self.loaded_processing_run_paths or [result.run_dir]
        self.load_processing_results_for_paths(run_paths, selected_output=result.output.output_file)
        stats_text = f"{result.area_km2:.3f} km2 | {result.mask_pixels:,} pixels"
        self.mask_stats_var.set(stats_text)
        self.status_var.set(f"Mask created: {stats_text}")
        messagebox.showinfo(
            "Mask complete",
            f"Mask pixels: {result.mask_pixels:,}\n"
            f"Valid pixels: {result.valid_pixels:,}\n"
            f"Water excluded: {result.water_excluded_pixels:,}\n"
            f"Cloud/QA excluded: {result.cloud_excluded_pixels:,}\n"
            f"Area: {result.area_km2:.3f} km2\n\n"
            f"Mask file:\n{result.output.output_file}\n\n"
            f"Manifest:\n{result.manifest}",
        )

    def boundary_finished(self, result: BoundaryResult | None, error: Exception | None) -> None:
        self.boundary_button.configure(state="normal")
        if error:
            self.status_var.set(f"Boundary extraction failed: {error}")
            messagebox.showerror("Boundary extraction failed", str(error))
            return
        if result is None:
            return
        run_paths = self.loaded_processing_run_paths or [result.run_dir]
        self.load_processing_results_for_paths(run_paths, selected_output=result.output.output_file)
        stats_text = f"{result.boundary_length_km:.3f} km boundary | {result.polygon_count:,} polygon(s)"
        self.mask_stats_var.set(stats_text)
        self.status_var.set(f"Boundary extracted: {stats_text}")
        messagebox.showinfo(
            "Boundary complete",
            f"Source mask pixels: {result.source_pixels:,}\n"
            f"Refined mask pixels: {result.refined_pixels:,}\n"
            f"Boundary pixels: {result.boundary_pixels:,}\n"
            f"Boundary length: {result.boundary_length_km:.3f} km\n"
            f"Polygons: {result.polygon_count:,}\n\n"
            f"Boundary raster:\n{result.output.output_file}\n\n"
            f"Boundary GeoJSON:\n{result.boundary_file}\n\n"
            f"Polygon GeoJSON:\n{result.polygon_file}\n\n"
            f"Manifest:\n{result.manifest}",
        )

    def overlay_finished(self, result: OverlayResult | None, error: Exception | None) -> None:
        self.overlay_button.configure(state="normal")
        if error:
            self.status_var.set(f"Overlay failed: {error}")
            messagebox.showerror("Overlay failed", str(error))
            return
        if result is None:
            return
        self.preview.show_image(str(result.output_file), preserve_view=False)
        self.preview_tabs.select(1)
        years = ", ".join(result.years)
        self.mask_stats_var.set(f"Overlay: {years}")
        self.status_var.set(f"Overlay created for {result.boundary_count} boundary result(s): {result.output_file}")
        self.show_details_text(
            "Boundary overlay\n"
            f"Years: {years}\n"
            f"Boundary results: {result.boundary_count}\n"
            f"Base raster: {result.base_file}\n"
            f"Output: {result.output_file}"
        )

    def processing_result_details(self, output: ProcessingOutput) -> str:
        size_label = "Boundary pixels" if output.kind == "Boundary" else "Mask pixels"
        metric_label = "Boundary length" if output.kind == "Boundary" else "Area"
        metric_unit = "km" if output.kind == "Boundary" else "km2"
        fields = [
            ("Run", output.run_name),
            ("Type", output.kind),
            ("Result", output.label),
            ("Scene ID", output.scene_id),
            ("Date", output.date),
            ("Sensor", output.sensor),
            ("Formula", output.formula),
            (size_label, f"{output.pixel_count:,}" if output.pixel_count else ""),
            (metric_label, f"{output.area_km2:.3f} {metric_unit}" if output.area_km2 else ""),
            ("Output", str(output.output_file)),
        ]
        return "\n".join(f"{label}: {value}" for label, value in fields if value)

    def copy_selected_scene_id(self) -> None:
        row = self.selected_row()
        if not row:
            return
        self.clipboard_clear()
        self.clipboard_append(row.get("item_id", ""))
        self.status_var.set("Scene ID copied to clipboard.")

    def copy_selected_preview_path(self) -> None:
        row = self.selected_row()
        if not row:
            return
        self.clipboard_clear()
        self.clipboard_append(row.get("preview_path", ""))
        self.status_var.set("Preview path copied to clipboard.")

    def reset_filters(self) -> None:
        self.sensor_var.set("All sensors")
        self.year_var.set("All years")
        self.cloud_var.set(25.0)
        self.search_var.set("")
        self.apply_filters()

def main() -> None:
    app = ImageryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
