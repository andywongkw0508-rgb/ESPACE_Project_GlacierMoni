from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..config import DATA_ROOT, DEFAULT_PREVIEW_SCENE_ID, MANIFEST


class FiltersMixin:
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
        self.status_var.set(
            f"Loaded {len(self.rows)} scenes from {MANIFEST.name}; showing {len(self.filtered_rows)}."
        )
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

    def reset_filters(self) -> None:
        self.sensor_var.set("All sensors")
        self.year_var.set("All years")
        self.cloud_var.set(25.0)
        self.search_var.set("")
        self.apply_filters()
