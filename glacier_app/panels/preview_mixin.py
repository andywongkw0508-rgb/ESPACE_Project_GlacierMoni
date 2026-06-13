from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import ttk

from .constants import _UI_FONT, _C_BORDER, _C_TREE_ALT
from ..bands import available_band_labels, band_preview_png, check_scene_bands
from ..preview import PreviewController


class PreviewMixin:
    def build_preview_panel(self, parent: ttk.PanedWindow) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        parent.add(panel, weight=2)
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        self._build_step_bar(panel)  # row=0

        viewer = ttk.Frame(panel, style="Card.TFrame")
        viewer.grid(row=1, column=0, sticky="nsew", pady=(8, 6))
        viewer.rowconfigure(0, weight=1)
        viewer.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            viewer, bg="#c6d9e0",
            highlightthickness=1, highlightbackground=_C_BORDER,
            cursor="fleur",
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        zoom_bar = ttk.Frame(panel, style="Card.TFrame")
        zoom_bar.grid(row=2, column=0, sticky="ew", pady=(0, 8))
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
        self.preview_tabs.grid(row=3, column=0, sticky="ew")

        # ── Bands tab ────────────────────────────────────────────────────────
        band_panel = ttk.Frame(self.preview_tabs, style="Card.TFrame", padding=8)
        self.preview_tabs.add(band_panel, text="  Bands  ")
        band_panel.columnconfigure(0, weight=1)
        ttk.Label(band_panel, text="Band Checker", style="Card.TLabel",
                  font=(_UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        band_columns = ("band", "disk", "manifest", "file")
        self.band_tree = ttk.Treeview(band_panel, columns=band_columns, show="headings",
                                      height=4, selectmode="browse")
        for col, heading, width in (
            ("band",     "Band",         80),
            ("disk",     "File",         50),
            ("manifest", "URL",          50),
            ("file",     "Matched file", 260),
        ):
            self.band_tree.heading(col, text=heading)
            self.band_tree.column(col, width=width, anchor="w", stretch=col == "file")
        self.band_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.band_tree.grid(row=1, column=0, sticky="ew")
        self.band_tree.bind("<<TreeviewSelect>>", self.on_band_selected)

        # ── Results tab ──────────────────────────────────────────────────────
        results_panel = ttk.Frame(self.preview_tabs, style="Card.TFrame", padding=8)
        self.preview_tabs.add(results_panel, text="  Results  ")
        results_panel.columnconfigure(0, weight=1)

        res_header = ttk.Frame(results_panel, style="Card.TFrame")
        res_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        res_header.columnconfigure(0, weight=1)
        ttk.Label(res_header, text="Processing Results", style="Card.TLabel",
                  font=(_UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        filter_combo = ttk.Combobox(
            res_header, textvariable=self.result_filter_var,
            values=["Index", "Mask", "Boundary", "All"],
            state="readonly", width=9,
        )
        filter_combo.grid(row=0, column=1, sticky="e")
        filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_processing_results())

        result_columns = ("run", "type", "result", "scene")
        self.result_tree = ttk.Treeview(results_panel, columns=result_columns, show="headings",
                                        height=4, selectmode="browse")
        for col, heading, width in (
            ("run",    "Run",      100),
            ("type",   "Type",      80),
            ("result", "Result",    70),
            ("scene",  "Scene ID", 260),
        ):
            self.result_tree.heading(col, text=heading)
            self.result_tree.column(col, width=width, anchor="w", stretch=col == "scene")
        self.result_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.result_tree.grid(row=1, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self.on_processing_result_selected)

        # ── threshold + stats ────────────────────────────────────────────────
        thresh_bar = ttk.Frame(results_panel, style="Card.TFrame")
        thresh_bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        thresh_bar.columnconfigure(2, weight=1)
        ttk.Label(thresh_bar, text="Threshold ≥", style="Card.Muted.TLabel").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(thresh_bar, textvariable=self.mask_threshold_var, width=7).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(thresh_bar, textvariable=self.mask_stats_var, style="Card.Muted.TLabel").grid(
            row=0, column=2, sticky="w")

        # ── action area: scope label | buttons ───────────────────────────────
        action_frame = ttk.Frame(results_panel, style="Card.TFrame")
        action_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        action_frame.columnconfigure(1, weight=1)

        ttk.Label(action_frame, text="Selected", style="Card.Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        single_inner = ttk.Frame(action_frame, style="Card.TFrame")
        single_inner.grid(row=0, column=1, sticky="ew")
        single_inner.columnconfigure(2, weight=1)
        self.mask_button = ttk.Button(single_inner, text="▶  Build Mask",
                                      style="Accent.TButton", command=self.build_selected_mask)
        self.mask_button.grid(row=0, column=0)
        self.boundary_button = ttk.Button(single_inner, text="Refined Boundary",
                                          command=self.extract_selected_boundary)
        self.boundary_button.grid(row=0, column=1, padx=(4, 0))
        self.overlay_button = ttk.Button(single_inner, text="Overlay Target",
                                         command=self.build_boundary_overlay)
        self.overlay_button.grid(row=0, column=2, sticky="e")

        ttk.Separator(action_frame, style="TSeparator").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(5, 5))

        ttk.Label(action_frame, text="All", style="Card.Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8))
        batch_inner = ttk.Frame(action_frame, style="Card.TFrame")
        batch_inner.grid(row=2, column=1, sticky="ew")
        batch_inner.columnconfigure(0, weight=1)
        batch_inner.columnconfigure(1, weight=1)
        self.batch_mask_button = ttk.Button(
            batch_inner, text="▶  Build All Masks",
            style="Accent.TButton", command=self.build_all_masks,
        )
        self.batch_mask_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.batch_boundary_button = ttk.Button(
            batch_inner, text="Extract All Boundaries",
            command=self.extract_all_boundaries,
        )
        self.batch_boundary_button.grid(row=0, column=1, sticky="ew")

    def _build_step_bar(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        steps = ["① Filter", "② Select", "③ Preprocess", "④ Analyse"]
        for i, text in enumerate(steps):
            lbl = ttk.Label(frame, text=text, style="Step.Inactive.TLabel", padding=(6, 3))
            lbl.pack(side="left")
            self._step_labels.append(lbl)
            if i < len(steps) - 1:
                ttk.Label(frame, text="→", style="Step.Inactive.TLabel").pack(side="left")
        self._update_step_bar()

    def _update_step_bar(self) -> None:
        for i, lbl in enumerate(self._step_labels):
            if i < self._workflow_step:
                lbl.configure(style="Step.Done.TLabel")
            elif i == self._workflow_step:
                lbl.configure(style="Step.Active.TLabel")
            else:
                lbl.configure(style="Step.Inactive.TLabel")

    def _advance_step(self, step: int) -> None:
        if step > self._workflow_step:
            self._workflow_step = step
            self._update_step_bar()

    def show_scene(self, row: dict[str, str]) -> None:
        self.current_scene_row = row
        self.update_band_checker(row)
        self.preview.show_image(row.get("preview_path", ""), preserve_view=False)
        self.show_details_text(self.scene_details(row))

    def show_details_text(self, text: str) -> None:
        pass

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
                    Path(str(check["matched_file"])).name if check["matched_file"] else "",
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
        self.status_var.set(f"Showing {check.get('label', 'band')} — {band_path}")
