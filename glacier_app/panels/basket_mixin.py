from __future__ import annotations

import csv
import json
from pathlib import Path
from tkinter import filedialog

from ..bands import check_scene_bands
from ..config import APP_DIR


class BasketMixin:
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
        self._advance_step(1)

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

    def focus_basket_scene(self, _event: object) -> None:
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
            "date", "sensor", "year", "item_id", "platform",
            "tile_or_path", "cloud_cover", "preview_path", "band_files_json",
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
                writer.writerow({
                    "date":           row.get("date", ""),
                    "sensor":         row.get("sensor", ""),
                    "year":           row.get("year", ""),
                    "item_id":        row.get("item_id", ""),
                    "platform":       row.get("platform", ""),
                    "tile_or_path":   row.get("tile_or_path", ""),
                    "cloud_cover":    row.get("cloud_cover", ""),
                    "preview_path":   row.get("preview_path", ""),
                    "band_files_json": json.dumps(band_files, ensure_ascii=True),
                })
        self.status_var.set(f"Exported {len(rows)} basket scenes to {output_path}")
