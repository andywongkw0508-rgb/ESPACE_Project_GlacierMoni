from __future__ import annotations

import csv
import datetime as dt
import json
import subprocess
import tkinter as tk
from fractions import Fraction
from pathlib import Path
from tkinter import filedialog, ttk


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_ROOT = PROJECT_ROOT / "data" / "vatnajokull_28WDS_by_band"
MANIFEST = DATA_ROOT / "master_manifest.csv"
GDAL_TRANSLATE = Path("C:/Program Files/QGIS 4.0.2/bin/gdal_translate.exe")
BAND_PREVIEW_CACHE = APP_DIR / "outputs" / "band_previews"

SENTINEL_BANDS = [
    ("visual", "Visual", "raw_visual_url"),
    ("blue_B02", "Blue B02", "raw_blue_B02_url"),
    ("green_B03", "Green B03", "raw_green_B03_url"),
    ("red_B04", "Red B04", "raw_red_B04_url"),
    ("nir_B08", "NIR B08", "raw_nir_B08_url"),
    ("swir_B11", "SWIR B11", "raw_swir_B11_url"),
    ("scene_classification_SCL", "SCL", "raw_scene_classification_SCL_url"),
]

LANDSAT_BANDS = [
    ("blue", "Blue", "raw_blue_url"),
    ("green", "Green", "raw_green_url"),
    ("red", "Red", "raw_red_url"),
    ("nir08", "NIR08", "raw_nir08_url"),
    ("swir16", "SWIR16", "raw_swir16_url"),
    ("qa_pixel", "QA Pixel", "raw_qa_pixel_url"),
]


class ImageryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Glacial Monster")
        self.geometry("1320x820")
        self.minsize(1060, 680)

        self.rows = self.load_rows()
        self.filtered_rows: list[dict[str, str]] = []
        self.original_preview_image: tk.PhotoImage | None = None
        self.preview_image: tk.PhotoImage | None = None
        self.preview_canvas_image_id: int | None = None
        self.preview_zoom = tk.IntVar(value=100)
        self.current_scene_row: dict[str, str] | None = None
        self.current_band_checks: list[dict[str, object]] = []
        self.basket_rows: dict[str, dict[str, str]] = {}

        self.sensor_var = tk.StringVar(value="All sensors")
        self.year_var = tk.StringVar(value="All years")
        self.cloud_var = tk.DoubleVar(value=25.0)
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

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

        ttk.Separator(panel).pack(fill="x", pady=14)
        ttk.Label(panel, text="Next modules", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        for item in ("Band checker", "QGIS preprocessing", "NDSI / NDWI masks", "AI training set"):
            ttk.Label(panel, text=f"- {item}", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

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
        ttk.Button(header, text="Remove", command=self.remove_selected_basket_scene).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(header, text="Clear", command=self.clear_basket).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(header, text="Export CSV", command=self.export_basket_csv).grid(row=0, column=3)

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
        self.basket_tree.grid(row=1, column=0, sticky="ew")
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
        self.preview_canvas.bind("<ButtonPress-1>", self.start_preview_pan)
        self.preview_canvas.bind("<B1-Motion>", self.move_preview_pan)
        self.preview_canvas.bind("<MouseWheel>", self.on_preview_mousewheel)
        self.preview_canvas.bind("<Button-4>", lambda event: self.zoom_preview(1))
        self.preview_canvas.bind("<Button-5>", lambda event: self.zoom_preview(-1))
        self.preview_canvas.bind("<Configure>", lambda _event: self.center_preview_if_needed())

        controls = ttk.Frame(panel, style="Panel.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(3, weight=1)
        ttk.Button(controls, text="-", width=3, command=lambda: self.zoom_preview(-1)).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(controls, text="+", width=3, command=lambda: self.zoom_preview(1)).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(controls, text="Fit", command=self.fit_preview).grid(row=0, column=2, padx=(0, 8))
        self.zoom_label = ttk.Label(controls, text="100%", style="Muted.TLabel")
        self.zoom_label.grid(row=0, column=3, sticky="w")

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

    def load_rows(self) -> list[dict[str, str]]:
        if not MANIFEST.exists():
            raise FileNotFoundError(f"Missing manifest: {MANIFEST}")

        rows: list[dict[str, str]] = []
        with MANIFEST.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["date"] = self.format_date(row.get("datetime", ""))
                row["cloud_value"] = self.parse_float(row.get("cloud_cover", ""))
                preview = row.get("preview_file", "")
                row["preview_path"] = str((PROJECT_ROOT / preview).resolve()) if preview else ""
                rows.append(row)
        return rows

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
            self.original_preview_image = None
            self.preview_image = None
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(170, 130, text="No scenes match the current filters.", fill="#617078")
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
        self.show_preview(row.get("preview_path", ""), preserve_view=False)
        self.show_details_text(self.scene_details(row))

    def show_preview(self, path_text: str, preserve_view: bool = False) -> None:
        path = Path(path_text)
        if not path.exists():
            self.original_preview_image = None
            self.preview_image = None
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(170, 130, text="Preview image is not available.", fill="#617078")
            return

        self.original_preview_image = tk.PhotoImage(file=str(path))
        if preserve_view:
            self.redraw_preview(center=False)
        else:
            self.fit_preview()

    def fit_preview(self) -> None:
        if not self.original_preview_image:
            return
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        image_width = self.original_preview_image.width()
        image_height = self.original_preview_image.height()
        fit_percent = min(100, int(min(canvas_width / image_width, canvas_height / image_height) * 100))
        self.preview_zoom.set(max(10, fit_percent))
        self.redraw_preview(center=True)

    def zoom_preview(self, direction: int) -> None:
        if not self.original_preview_image:
            return
        levels = [10, 15, 20, 25, 33, 50, 67, 100, 150, 200, 300, 400]
        current = self.preview_zoom.get()
        nearest_index = min(range(len(levels)), key=lambda index: abs(levels[index] - current))
        next_index = max(0, min(len(levels) - 1, nearest_index + direction))
        self.preview_zoom.set(levels[next_index])
        self.redraw_preview(center=False)

    def redraw_preview(self, center: bool) -> None:
        if not self.original_preview_image:
            return
        zoom = self.preview_zoom.get()
        image = self.resample_preview(self.original_preview_image, zoom)
        self.preview_image = image
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        viewport_x = self.preview_canvas.canvasx(canvas_width // 2)
        viewport_y = self.preview_canvas.canvasy(canvas_height // 2)
        offset_x = 0.0
        offset_y = 0.0
        if not center and self.preview_canvas_image_id is not None:
            coords = self.preview_canvas.coords(self.preview_canvas_image_id)
            if len(coords) >= 2:
                offset_x = viewport_x - coords[0]
                offset_y = viewport_y - coords[1]

        self.preview_canvas.delete("all")
        if center:
            x = canvas_width // 2
            y = canvas_height // 2
        else:
            x = viewport_x - offset_x
            y = viewport_y - offset_y
        self.preview_canvas_image_id = self.preview_canvas.create_image(x, y, image=image, anchor="center")
        bounds = self.preview_canvas.bbox(self.preview_canvas_image_id)
        if bounds:
            self.preview_canvas.configure(scrollregion=bounds)
        self.zoom_label.configure(text=f"{zoom}%")

    def resample_preview(self, image: tk.PhotoImage, zoom_percent: int) -> tk.PhotoImage:
        if zoom_percent == 100:
            return image.copy()
        ratio = Fraction(zoom_percent, 100).limit_denominator(8)
        scaled = image.copy()
        if ratio.numerator > 1:
            scaled = scaled.zoom(ratio.numerator)
        if ratio.denominator > 1:
            scaled = scaled.subsample(ratio.denominator)
        return scaled

    def start_preview_pan(self, event: tk.Event) -> None:
        self.preview_canvas.scan_mark(event.x, event.y)

    def move_preview_pan(self, event: tk.Event) -> None:
        self.preview_canvas.scan_dragto(event.x, event.y, gain=1)

    def on_preview_mousewheel(self, event: tk.Event) -> None:
        self.zoom_preview(1 if event.delta > 0 else -1)

    def center_preview_if_needed(self) -> None:
        if self.preview_canvas_image_id is None and self.original_preview_image:
            self.fit_preview()

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

        available = self.available_band_labels(row)
        lines = [f"{label}: {value}" for label, value in fields]
        lines.append("")
        lines.append("Available raw assets:")
        lines.extend(f"- {band}" for band in available)
        return "\n".join(lines)

    def available_band_labels(self, row: dict[str, str]) -> list[str]:
        labels = []
        band_columns = {
            "raw_visual_url": "visual",
            "raw_blue_B02_url": "Sentinel blue B02",
            "raw_green_B03_url": "Sentinel green B03",
            "raw_red_B04_url": "Sentinel red B04",
            "raw_nir_B08_url": "Sentinel NIR B08",
            "raw_swir_B11_url": "Sentinel SWIR B11",
            "raw_scene_classification_SCL_url": "Sentinel SCL",
            "raw_blue_url": "Landsat blue",
            "raw_green_url": "Landsat green",
            "raw_red_url": "Landsat red",
            "raw_nir08_url": "Landsat NIR",
            "raw_swir16_url": "Landsat SWIR",
            "raw_qa_pixel_url": "Landsat QA pixel",
        }
        for column, label in band_columns.items():
            if row.get(column):
                labels.append(label)
        return labels or ["No raw assets listed"]

    def update_band_checker(self, row: dict[str, str]) -> None:
        self.clear_band_checker()
        checks = self.check_scene_bands(row)
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
            preview_path = self.band_preview_png(Path(str(band_path)), str(check.get("label", "band")))
        except RuntimeError as exc:
            self.status_var.set(str(exc))
            return
        self.show_preview(str(preview_path), preserve_view=True)
        self.status_var.set(f"Showing {check.get('label', 'band')} band preview.")

    def band_preview_png(self, tif_path: Path, label: str) -> Path:
        if not GDAL_TRANSLATE.exists():
            raise RuntimeError(f"Cannot create band preview; missing GDAL: {GDAL_TRANSLATE}")
        BAND_PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(char if char.isalnum() else "_" for char in label).strip("_")
        preview_path = BAND_PREVIEW_CACHE / f"{tif_path.stem}_{safe_label}.png"
        if preview_path.exists() and preview_path.stat().st_mtime >= tif_path.stat().st_mtime:
            return preview_path

        command = [
            str(GDAL_TRANSLATE),
            "-of",
            "PNG",
            "-ot",
            "Byte",
            "-outsize",
            "1600",
            "0",
            "-scale",
            str(tif_path),
            str(preview_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0 or not preview_path.exists():
            details = (result.stderr or result.stdout or "unknown GDAL error").strip().splitlines()
            message = details[-1] if details else "unknown GDAL error"
            raise RuntimeError(f"Could not render {label} preview: {message}")
        return preview_path


    def check_scene_bands(self, row: dict[str, str]) -> list[dict[str, object]]:
        sensor = row.get("sensor", "")
        year = row.get("year", "")
        item_id = row.get("item_id", "")
        if sensor == "sentinel-2-l2a":
            sensor_folder = "sentinel"
            band_specs = SENTINEL_BANDS
        elif sensor == "landsat-c2-l2":
            sensor_folder = "landsat"
            band_specs = LANDSAT_BANDS
        else:
            return []

        checks = []
        file_patterns = self.scene_file_patterns(row)
        for folder, label, manifest_column in band_specs:
            band_dir = DATA_ROOT / sensor_folder / folder / year
            matches = []
            if band_dir.exists():
                for pattern in file_patterns:
                    matches = sorted(band_dir.glob(pattern))
                    if matches:
                        break
            matched_file = matches[0].name if matches else ""
            matched_path = str(matches[0]) if matches else ""
            checks.append(
                {
                    "label": label,
                    "disk_exists": bool(matches),
                    "manifest_url": bool(row.get(manifest_column, "")),
                    "matched_file": matched_file,
                    "matched_path": matched_path,
                }
            )
        return checks

    def scene_file_patterns(self, row: dict[str, str]) -> list[str]:
        item_id = row.get("item_id", "")
        date = row.get("date", "")
        patterns = [f"*{item_id}*.tif"] if item_id else []

        parts = item_id.split("_")
        if row.get("sensor") == "sentinel-2-l2a" and len(parts) >= 5:
            platform = parts[0]
            acquisition = parts[2]
            orbit = parts[3]
            tile = parts[4]
            patterns.append(f"{date}_{platform}_MSIL2A_{acquisition}_{orbit}_{tile}_*.tif")
        elif row.get("sensor") == "landsat-c2-l2" and len(parts) >= 6:
            platform = parts[0]
            level = parts[1]
            path_row = parts[2]
            acquisition_date = parts[3]
            collection = parts[4]
            tier = parts[5]
            patterns.append(f"{date}_{platform}_{level}_{path_row}_{acquisition_date}_{collection}_{tier}_*.tif")

        return patterns

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
                    for check in self.check_scene_bands(row)
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

    @staticmethod
    def parse_float(value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 100.0

    @staticmethod
    def format_date(value: str) -> str:
        if not value:
            return ""
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return value[:10]


def main() -> None:
    app = ImageryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
