from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from osgeo import gdal as _gdal
_gdal.SetCacheMax(512 * 1024 * 1024)  # 512 MB GDAL block cache

from .config import DEFAULT_SENTINEL_PREPROCESS_RESOLUTION
from .data import load_rows
from .preview import PreviewController
from .results import ProcessingOutput
from .panels import (
    AnalysisMixin,
    BasketMixin,
    FiltersMixin,
    MaskBoundaryMixin,
    PreprocessMixin,
    PreviewMixin,
    ProgressMixin,
    StyleMixin,
    WorkflowMixin,
)


class ImageryApp(
    StyleMixin,
    ProgressMixin,
    FiltersMixin,
    PreviewMixin,
    WorkflowMixin,
    BasketMixin,
    PreprocessMixin,
    AnalysisMixin,
    MaskBoundaryMixin,
    tk.Tk,
):
    def __init__(self) -> None:
        super().__init__()
        self.title("Glacier Monitoring Workbench")
        self.geometry("1360x840")
        self.minsize(760, 520)
        self._base_tk_scaling = float(self.tk.call("tk", "scaling"))
        self._current_ui_scale = 1.0
        self._resize_job: str | None = None

        # ── data ────────────────────────────────────────────────────────────
        self.rows = load_rows()
        self.filtered_rows: list[dict[str, str]] = []
        self.basket_rows: dict[str, dict[str, str]] = {}

        # ── scene/band state ────────────────────────────────────────────────
        self.preview: PreviewController | None = None
        self.current_scene_row: dict[str, str] | None = None
        self.current_band_checks: list[dict[str, object]] = []
        self.startup_preview_shown = False

        # ── processing state ────────────────────────────────────────────────
        self.current_processing_outputs: list[ProcessingOutput] = []
        self.loaded_processing_run_paths: list[Path] = []
        self._displayed_outputs: list[ProcessingOutput] = []
        self._preview_request_id = 0

        # ── ui variables ────────────────────────────────────────────────────
        self.sensor_var              = tk.StringVar(value="All sensors")
        self.year_var                = tk.StringVar(value="All years")
        self.cloud_var               = tk.DoubleVar(value=25.0)
        self.search_var              = tk.StringVar(value="")
        self.status_var              = tk.StringVar(value="")
        self.sentinel_resolution_var = tk.StringVar(value=DEFAULT_SENTINEL_PREPROCESS_RESOLUTION)
        self.cloud_mask_var          = tk.BooleanVar(value=True)
        self.mask_threshold_var      = tk.StringVar(value="0.40")
        self.mask_stats_var          = tk.StringVar(value="")
        self.result_filter_var       = tk.StringVar(value="Index")
        self._prefer_chlorophyll_result = False
        self._prefer_processing_result_label: str | None = None

        # ── workflow step bar ────────────────────────────────────────────────
        self._workflow_step = 0
        self._step_labels: list[ttk.Label] = []

        # ── progress dialog ──────────────────────────────────────────────────
        self._progress_dialog: tk.Toplevel | None = None

        self.configure_style()
        self.build_layout()
        self.apply_filters()
        self.bind("<Configure>", self._schedule_responsive_update)

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
        self.build_top_toolbar()
        ttk.Separator(self).pack(fill="x")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        self.build_filters(body)
        self.build_preview_panel(body)
        self.build_workflow_panel(body)

        status_bar = ttk.Frame(self, style="TFrame")
        status_bar.pack(fill="x", side="bottom")
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w",
                  padding=(16, 5), style="Status.TLabel").pack(fill="x")

    def build_top_toolbar(self) -> None:
        self.toolbar = ttk.Frame(self, padding=(16, 6, 16, 4), style="TFrame")
        self.toolbar.pack(fill="x")
        self.toolbar_buttons = []

        self.chlorophyll_button = ttk.Button(
            self.toolbar,
            text="Chlorophyll-a Map",
            style="Accent.TButton",
            command=self.calculate_selected_chlorophyll_map,
        )
        self.toolbar_buttons.append(self.chlorophyll_button)
        self.chlorophyll_overlay_button = ttk.Button(
            self.toolbar,
            text="CHL Overlay",
            command=self.overlay_selected_chlorophyll_map,
        )
        self.toolbar_buttons.append(self.chlorophyll_overlay_button)
        self.turbidity_button = ttk.Button(
            self.toolbar,
            text="Turbidity Map",
            command=self.calculate_selected_turbidity_warning,
        )
        self.toolbar_buttons.append(self.turbidity_button)
        self.turbidity_overlay_button = ttk.Button(
            self.toolbar,
            text="Turb Overlay",
            command=self.overlay_selected_turbidity_map,
        )
        self.toolbar_buttons.append(self.turbidity_overlay_button)
        self.dashboard_button = ttk.Button(
            self.toolbar,
            text="Dashboard",
            command=self.open_dashboard,
        )
        self.toolbar_buttons.append(self.dashboard_button)
        self._layout_top_toolbar(1360)

    def _layout_top_toolbar(self, width: int) -> None:
        if not hasattr(self, "toolbar_buttons"):
            return
        for button in self.toolbar_buttons:
            button.grid_forget()
        for column in range(5):
            self.toolbar.columnconfigure(column, weight=0)

        columns = max(1, len(self.toolbar_buttons))
        if width < 520:
            columns = 1
        for index, button in enumerate(self.toolbar_buttons):
            row = index // columns
            column = index % columns
            button.grid(row=row, column=column, sticky="w", padx=(0, 6), pady=(0, 2))

    def _schedule_responsive_update(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, lambda: self._apply_responsive_scale(event.width, event.height))

    def _apply_responsive_scale(self, width: int, height: int) -> None:
        self._resize_job = None
        scale = min(1.0, max(0.75, min(width / 1120, height / 760)))
        if abs(scale - self._current_ui_scale) >= 0.03:
            self._current_ui_scale = scale
            self.tk.call("tk", "scaling", self._base_tk_scaling * scale)
            self.configure_scaled_style(scale)
        self._resize_tables(height)
        self._layout_top_toolbar(width)

    def _resize_tables(self, height: int) -> None:
        compact = height < 700
        very_compact = height < 590
        sizes = {
            "tree": 3 if very_compact else 5 if compact else 7,
            "basket_tree": 2 if compact else 3,
            "runs_tree": 2 if compact else 3,
            "band_tree": 2 if very_compact else 3 if compact else 4,
            "result_tree": 2 if very_compact else 3 if compact else 4,
        }
        for name, rows in sizes.items():
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(height=rows)


def main() -> None:
    app = ImageryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
