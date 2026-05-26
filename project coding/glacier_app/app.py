from __future__ import annotations

import csv
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .bands import available_band_labels, band_preview_png, check_scene_bands
from .config import (
    APP_DIR,
    DATA_ROOT,
    DEFAULT_SENTINEL_PREPROCESS_RESOLUTION,
    MANIFEST,
    SENTINEL_PREPROCESS_RESOLUTIONS,
)
from .data import load_rows
from .indexes import IndexResult, calculate_run_indexes
from .preprocessing import PreprocessResult, delete_preprocess_run, list_preprocess_runs, preprocess_rows
from .preview import PreviewController


class ImageryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Glacial Monster")
        self.geometry("1320x820")
        self.minsize(1060, 680)

        self.rows = load_rows()
        self.filtered_rows: list[dict[str, str]] = []
        self.preview: PreviewController | None = None
        self.current_scene_row: dict[str, str] | None = None
        self.current_band_checks: list[dict[str, object]] = []
        self.basket_rows: dict[str, dict[str, str]] = {}

        self.sensor_var = tk.StringVar(value="All sensors")
        self.year_var = tk.StringVar(value="All years")
        self.cloud_var = tk.DoubleVar(value=25.0)
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.sentinel_resolution_var = tk.StringVar(value=DEFAULT_SENTINEL_PREPROCESS_RESOLUTION)

        self.configure_style()
        self.build_layout()
        self.apply_filters()

    def configure_style(self) -> None:
        self.configure(bg="#f4f7f7")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f7f7")
        style.configure("Panel.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("Header.TLabel", background="#f4f7f7", foreground="#152328", font=("Segoe UI", 18, "bold"))
        style.configure("Subheader.TLabel", background="#f4f7f7", foreground="#5d6b72", font=("Segoe UI", 10))
        style.configure("TLabel", background="#ffffff", foreground="#1f2d33", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#617078", font=("Segoe UI", 9))
        style.configure("Metric.TLabel", background="#ffffff", foreground="#1f2d33", font=("Segoe UI", 16, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=28, background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#e6eeee", foreground="#1f2d33")

    def build_layout(self) -> None:
        header = ttk.Frame(self, padding=(18, 16, 18, 8))
        header.pack(fill="x")

        ttk.Label(header, text="Glacier Monitoring Workbench", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Scene inspection and selection interface for the prepared band-separated satellite imagery.",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(18, 8, 18, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=270)
        body.columnconfigure(1, weight=1, minsize=440)
        body.columnconfigure(2, weight=1, minsize=560)
        body.rowconfigure(0, weight=1)

        self.build_filters(body)
        self.build_table(body)
        self.build_details(body)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(18, 6), background="#e7eeee")
        status.pack(fill="x", side="bottom")

    def build_filters(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        ttk.Label(panel, text="Filters", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Choose scenes for inspection and later processing.", style="Muted.TLabel").pack(
            anchor="w", pady=(3, 14)
        )

        years = ["All years"] + sorted({row["year"] for row in self.rows})
        sensors = ["All sensors"] + sorted({row["sensor"] for row in self.rows})

        self.add_combo(panel, "Sensor", self.sensor_var, sensors)
        self.add_combo(panel, "Year", self.year_var, years)

        ttk.Label(panel, text="Max cloud cover (%)").pack(anchor="w", pady=(12, 4))
        cloud = ttk.Scale(panel, from_=0, to=100, variable=self.cloud_var, command=lambda _value: self.apply_filters())
        cloud.pack(fill="x")
        self.cloud_label = ttk.Label(panel, text="", style="Muted.TLabel")
        self.cloud_label.pack(anchor="w", pady=(3, 0))

        ttk.Label(panel, text="Search scene ID").pack(anchor="w", pady=(12, 4))
        search = ttk.Entry(panel, textvariable=self.search_var)
        search.pack(fill="x")
        search.bind("<KeyRelease>", lambda _event: self.apply_filters())

        ttk.Button(panel, text="Reset Filters", command=self.reset_filters).pack(fill="x", pady=(16, 8))

        ttk.Separator(panel).pack(fill="x", pady=14)
        ttk.Label(panel, text="Dataset", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(panel, text=str(DATA_ROOT), style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(4, 12))

        self.metric_total = ttk.Label(panel, text="0", style="Metric.TLabel")
        self.metric_total.pack(anchor="w")
        ttk.Label(panel, text="matching scenes", style="Muted.TLabel").pack(anchor="w")

        self.build_run_manager(panel)

        #ttk.Separator(panel).pack(fill="x", pady=14)
        #ttk.Label(panel, text="Next modules", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        #for item in ("Band checker", "QGIS preprocessing", "NDSI / NDWI masks", "AI training set"):
        #    ttk.Label(panel, text=f"- {item}", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

    def build_run_manager(self, parent: ttk.Frame) -> None:
        ttk.Separator(parent).pack(fill="x", pady=14)
        ttk.Label(parent, text="Preprocessing Runs", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Select one or more old output folders to delete.", style="Muted.TLabel", wraplength=230).pack(
            anchor="w", pady=(3, 8)
        )

        columns = ("run", "rasters", "modified")
        self.runs_tree = ttk.Treeview(parent, columns=columns, show="headings", height=5, selectmode="extended")
        for column, heading, width in (
            ("run", "Run", 112),
            ("rasters", "Files", 44),
            ("modified", "Modified", 88),
        ):
            self.runs_tree.heading(column, text=heading)
            self.runs_tree.column(column, width=width, anchor="w", stretch=column == "run")
        self.runs_tree.pack(fill="x")

        buttons = ttk.Frame(parent, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(8, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Refresh", command=self.refresh_preprocess_runs).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Delete Selected", command=self.delete_selected_preprocess_run).grid(
            row=0, column=1, sticky="ew"
        )
        self.index_button = ttk.Button(buttons, text="Calculate Indexes", command=self.calculate_selected_indexes)
        self.index_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.refresh_preprocess_runs()

    def build_table(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        panel.rowconfigure(1, weight=1)
        panel.rowconfigure(3, weight=0)
        panel.columnconfigure(0, weight=1)

        table_header = ttk.Frame(panel, style="Panel.TFrame")
        table_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        table_header.columnconfigure(0, weight=1)
        ttk.Label(table_header, text="Scene Inventory", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(table_header, text="Add To Basket", command=self.add_selected_scene_to_basket).grid(
            row=0, column=1, sticky="e"
        )

        columns = ("date", "sensor", "cloud", "platform", "tile")
        self.tree = ttk.Treeview(panel, columns=columns, show="headings", selectmode="browse")
        headings = {
            "date": "Date",
            "sensor": "Sensor",
            "cloud": "Cloud %",
            "platform": "Platform",
            "tile": "Tile / Path",
        }
        widths = {"date": 115, "sensor": 120, "cloud": 80, "platform": 120, "tile": 105}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w", stretch=column in {"sensor", "platform"})

        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_scene_selected)
        self.tree.bind("<Double-1>", lambda _event: self.add_selected_scene_to_basket())

        self.build_basket(panel)

    def build_basket(self, parent: ttk.Frame) -> None:
        basket_panel = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 12, 0, 0))
        basket_panel.grid(row=2, column=0, columnspan=2, sticky="ew")
        basket_panel.columnconfigure(0, weight=1)

        header = ttk.Frame(basket_panel, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        self.basket_label = ttk.Label(header, text="Scene Selection Basket (0)", font=("Segoe UI", 12, "bold"))
        self.basket_label.grid(row=0, column=0, sticky="w")

        controls = ttk.Frame(basket_panel, style="Panel.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(6, weight=1)
        ttk.Label(controls, text="Sentinel resolution (m)", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 4))
        self.sentinel_resolution_combo = ttk.Combobox(
            controls,
            textvariable=self.sentinel_resolution_var,
            values=SENTINEL_PREPROCESS_RESOLUTIONS,
            state="readonly",
            width=4,
        )
        self.sentinel_resolution_combo.grid(row=0, column=1, padx=(0, 10))
        ttk.Button(controls, text="Remove", command=self.remove_selected_basket_scene).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(controls, text="Clear", command=self.clear_basket).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(controls, text="Export CSV", command=self.export_basket_csv).grid(row=0, column=4, padx=(0, 6))
        self.preprocess_button = ttk.Button(controls, text="Run Preprocessing", command=self.run_preprocessing)
        self.preprocess_button.grid(row=0, column=5)

        basket_columns = ("date", "sensor", "cloud", "item")
        self.basket_tree = ttk.Treeview(basket_panel, columns=basket_columns, show="headings", height=5, selectmode="browse")
        for column, heading, width in (
            ("date", "Date", 90),
            ("sensor", "Sensor", 110),
            ("cloud", "Cloud %", 70),
            ("item", "Scene ID", 320),
        ):
            self.basket_tree.heading(column, text=heading)
            self.basket_tree.column(column, width=width, anchor="w", stretch=column == "item")
        self.basket_tree.grid(row=2, column=0, sticky="ew")
        self.basket_tree.bind("<Double-1>", self.focus_basket_scene)

    def build_details(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        panel.grid(row=0, column=2, sticky="nsew")
        panel.rowconfigure(4, weight=1)
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="Preview", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")

        viewer = ttk.Frame(panel, style="Panel.TFrame")
        viewer.grid(row=1, column=0, sticky="nsew", pady=(10, 8))
        viewer.rowconfigure(0, weight=1)
        viewer.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            viewer,
            width=540,
            height=420,
            bg="#cfe1e7",
            highlightthickness=1,
            highlightbackground="#c6d2d6",
            cursor="fleur",
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(panel, style="Panel.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(3, weight=1)
        ttk.Button(controls, text="-", width=3, command=lambda: self.preview.zoom_by(-1)).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(controls, text="+", width=3, command=lambda: self.preview.zoom_by(1)).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(controls, text="Fit", command=lambda: self.preview.fit()).grid(row=0, column=2, padx=(0, 8))
        self.zoom_label = ttk.Label(controls, text="100%", style="Muted.TLabel")
        self.zoom_label.grid(row=0, column=3, sticky="w")
        self.preview = PreviewController(self.preview_canvas, self.zoom_label)
        self.preview_canvas.bind("<ButtonPress-1>", self.preview.start_pan)
        self.preview_canvas.bind("<B1-Motion>", self.preview.move_pan)
        self.preview_canvas.bind("<MouseWheel>", self.preview.mousewheel)
        self.preview_canvas.bind("<Button-4>", lambda event: self.preview.zoom_by(1))
        self.preview_canvas.bind("<Button-5>", lambda event: self.preview.zoom_by(-1))
        self.preview_canvas.bind("<Configure>", lambda _event: self.preview.center_if_needed())

        band_panel = ttk.Frame(panel, style="Panel.TFrame", padding=8)
        band_panel.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        band_panel.columnconfigure(0, weight=1)
        ttk.Label(band_panel, text="Band Checker", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            band_panel,
            text="Select a band row to view it in the preview window.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 6))

        band_columns = ("band", "disk", "manifest", "file")
        self.band_tree = ttk.Treeview(band_panel, columns=band_columns, show="headings", height=7, selectmode="browse")
        for column, heading, width in (
            ("band", "Band", 86),
            ("disk", "File", 62),
            ("manifest", "URL", 62),
            ("file", "Matched file", 300),
        ):
            self.band_tree.heading(column, text=heading)
            self.band_tree.column(column, width=width, anchor="w", stretch=column == "file")
        self.band_tree.grid(row=2, column=0, sticky="ew")
        self.band_tree.bind("<<TreeviewSelect>>", self.on_band_selected)

        self.detail_text = tk.Text(
            panel,
            height=9,
            wrap="word",
            borderwidth=1,
            relief="solid",
            bg="#fbfdfd",
            fg="#1f2d33",
            font=("Consolas", 9),
        )
        self.detail_text.grid(row=4, column=0, sticky="nsew")
        self.detail_text.configure(state="disabled")

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Copy Scene ID", command=self.copy_selected_scene_id).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Copy Preview Path", command=self.copy_selected_preview_path).grid(row=0, column=1, sticky="ew")

    def add_combo(self, parent: ttk.Frame, label: str, variable: tk.StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 4))
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
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
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.show_scene(self.filtered_rows[0])
        else:
            self.preview.show_message("No scenes match the current filters.")
            self.clear_band_checker()
            self.show_details_text("No scene selected.")

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
        for row in rows:
            item_id = row.get("item_id", "")
            self.basket_tree.insert(
                "",
                "end",
                iid=item_id,
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
        self.preprocess_button.configure(state="disabled")
        self.status_var.set(
            f"Starting preprocessing for {len(rows)} scene(s). Sentinel: {sentinel_resolution} m; Landsat: 30 m."
        )
        worker = threading.Thread(target=self.preprocess_worker, args=(rows, sentinel_resolution), daemon=True)
        worker.start()

    def preprocess_worker(self, rows: list[dict[str, str]], sentinel_resolution: str) -> None:
        try:
            result = preprocess_rows(
                rows,
                sentinel_resolution=sentinel_resolution,
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
        messagebox.showinfo(
            "Index calculation complete",
            f"Index rasters written: {index_count}\n"
            f"Scenes scanned: {scene_count}\n\n"
            f"Manifest file(s):\n{manifest_lines}",
        )

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
