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
        self.minsize(960, 780)

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

        # ── workflow step bar ────────────────────────────────────────────────
        self._workflow_step = 0
        self._step_labels: list[ttk.Label] = []

        # ── progress dialog ──────────────────────────────────────────────────
        self._progress_dialog: tk.Toplevel | None = None

        self.configure_style()
        self.build_layout()
        self.apply_filters()

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
        self.build_preview_panel(body)
        self.build_workflow_panel(body)

        status_bar = ttk.Frame(self, style="TFrame")
        status_bar.pack(fill="x", side="bottom")
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w",
                  padding=(16, 5), style="Status.TLabel").pack(fill="x")


def main() -> None:
    app = ImageryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
