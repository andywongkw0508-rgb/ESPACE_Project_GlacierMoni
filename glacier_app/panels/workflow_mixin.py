from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .constants import _UI_FONT, _C_TREE_ALT
from ..config import SENTINEL_PREPROCESS_RESOLUTIONS


class WorkflowMixin:
    def build_workflow_panel(self, parent: ttk.PanedWindow) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=14)
        parent.add(panel, weight=1)
        panel.columnconfigure(0, weight=1)

        # ── Scene Inventory ──────────────────────────────────────────────────
        inv_header = ttk.Frame(panel, style="Card.TFrame")
        inv_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        inv_header.columnconfigure(0, weight=1)
        ttk.Label(inv_header, text="Scene Inventory", style="Card.TLabel",
                  font=(_UI_FONT, 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(inv_header, text="+ Add to Basket", style="Accent.TButton",
                   command=self.add_selected_scene_to_basket).grid(row=0, column=1, sticky="e")

        inv_columns = ("date", "sensor", "cloud", "platform", "tile")
        self.tree = ttk.Treeview(panel, columns=inv_columns, show="headings",
                                 height=7, selectmode="browse")
        inv_headings = {"date": "Date", "sensor": "Sensor", "cloud": "Cloud %",
                        "platform": "Platform", "tile": "Tile / Path"}
        inv_widths = {"date": 100, "sensor": 100, "cloud": 64, "platform": 86, "tile": 78}
        for col in inv_columns:
            self.tree.heading(col, text=inv_headings[col])
            self.tree.column(col, width=inv_widths[col], anchor="w",
                             stretch=col in {"sensor", "platform"})
        self.tree.tag_configure("odd", background=_C_TREE_ALT)
        inv_scroll = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=inv_scroll.set)
        self.tree.grid(row=1, column=0, sticky="ew")
        inv_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_scene_selected)
        self.tree.bind("<Double-1>", lambda _event: self.add_selected_scene_to_basket())
        self.tree.bind("<Button-2>", self._show_inventory_context_menu)
        self.tree.bind("<Button-3>", self._show_inventory_context_menu)

        ttk.Separator(panel).grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)

        # ── Scene Selection Basket ───────────────────────────────────────────
        bk_header = ttk.Frame(panel, style="Card.TFrame")
        bk_header.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        bk_header.columnconfigure(0, weight=1)
        self.basket_label = ttk.Label(
            bk_header, text="Scene Selection Basket (0)",
            style="Card.TLabel", font=(_UI_FONT, 11, "bold"),
        )
        self.basket_label.grid(row=0, column=0, sticky="w")

        bk_controls = ttk.Frame(panel, style="Card.TFrame")
        bk_controls.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        bk_controls.columnconfigure(4, weight=1)
        ttk.Label(bk_controls, text="Sentinel res. (m)", style="Card.Muted.TLabel").grid(
            row=0, column=0, padx=(0, 4))
        self.sentinel_resolution_combo = ttk.Combobox(
            bk_controls, textvariable=self.sentinel_resolution_var,
            values=SENTINEL_PREPROCESS_RESOLUTIONS, state="readonly", width=4,
        )
        self.sentinel_resolution_combo.grid(row=0, column=1, padx=(0, 12))
        ttk.Button(bk_controls, text="Remove", command=self.remove_selected_basket_scene).grid(
            row=0, column=2, padx=(0, 4))
        ttk.Button(bk_controls, text="Clear", command=self.clear_basket).grid(
            row=0, column=3, padx=(0, 4))
        ttk.Button(bk_controls, text="Export CSV", command=self.export_basket_csv).grid(
            row=0, column=4, sticky="e")

        self.preprocess_button = ttk.Button(
            panel, text="▶  Run Preprocessing", style="Accent.TButton",
            command=self.run_preprocessing,
        )
        self.preprocess_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        bk_columns = ("date", "sensor", "cloud", "item")
        self.basket_tree = ttk.Treeview(panel, columns=bk_columns, show="headings",
                                        height=3, selectmode="browse")
        for col, heading, width in (
            ("date",   "Date",     88),
            ("sensor", "Sensor",  100),
            ("cloud",  "Cloud %",  64),
            ("item",   "Scene ID", 234),
        ):
            self.basket_tree.heading(col, text=heading)
            self.basket_tree.column(col, width=width, anchor="w", stretch=col == "item")
        self.basket_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.basket_tree.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.basket_tree.bind("<Double-1>", self.focus_basket_scene)

        ttk.Separator(panel).grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)

        # ── Pipeline Runs ────────────────────────────────────────────────────
        ttk.Label(panel, text="Pipeline Runs", style="Card.TLabel",
                  font=(_UI_FONT, 11, "bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(0, 6))

        run_columns = ("run", "rasters", "modified")
        self.runs_tree = ttk.Treeview(
            panel, columns=run_columns, show="headings", height=3, selectmode="extended",
        )
        for col, heading, width in (
            ("run",      "Run",      188),
            ("rasters",  "Files",     42),
            ("modified", "Modified", 104),
        ):
            self.runs_tree.heading(col, text=heading)
            self.runs_tree.column(col, width=width, anchor="w", stretch=col == "run")
        self.runs_tree.tag_configure("odd", background=_C_TREE_ALT)
        self.runs_tree.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.runs_tree.bind("<<TreeviewSelect>>", self._on_run_selected)

        run_btns = ttk.Frame(panel, style="Card.TFrame")
        run_btns.grid(row=10, column=0, columnspan=2, sticky="ew")
        run_btns.columnconfigure(0, weight=1)
        run_btns.columnconfigure(1, weight=1)
        ttk.Button(run_btns, text="Refresh", command=self.refresh_preprocess_runs).grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ttk.Button(run_btns, text="Delete", command=self.delete_selected_preprocess_run).grid(
            row=0, column=1, sticky="ew", pady=(0, 4))
        self.index_button = ttk.Button(
            run_btns, text="Calculate Indexes",
            style="Accent.TButton", command=self.calculate_selected_indexes,
        )
        self.index_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Button(run_btns, text="Load Results", command=self.load_selected_processing_results).grid(
            row=2, column=0, columnspan=2, sticky="ew")

        self.refresh_preprocess_runs()

    def _on_run_selected(self, _event: tk.Event) -> None:
        pass

    def _show_inventory_context_menu(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.show_scene(self.filtered_rows[int(iid)])
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Add to Basket", command=self.add_selected_scene_to_basket)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_scene_selected(self, _event: tk.Event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.filtered_rows[int(selection[0])]
        self.show_scene(row)

    def selected_row(self) -> dict[str, str] | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.filtered_rows[int(selection[0])]

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
