from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

from ..preprocessing import PreprocessResult, delete_preprocess_run, list_preprocess_runs, preprocess_rows


class PreprocessMixin:
    def run_preprocessing(self) -> None:
        if not self.basket_rows:
            self.status_var.set("Add scenes to the basket before preprocessing.")
            return
        rows = sorted(self.basket_rows.values(), key=lambda item: (item.get("date", ""), item.get("sensor", "")))
        sentinel_resolution = self.sentinel_resolution_var.get()
        cloud_mask = self.cloud_mask_var.get()
        self.preprocess_button.configure(state="disabled")
        self._advance_step(2)
        init_msg = (
            f"Preprocessing {len(rows)} scene(s) — Sentinel {sentinel_resolution} m / Landsat 30 m"
            + (" + cloud mask" if cloud_mask else "")
        )
        self.status_var.set(init_msg)
        self._open_progress_dialog("Preprocessing", init_msg)
        worker = threading.Thread(
            target=self.preprocess_worker, args=(rows, sentinel_resolution, cloud_mask), daemon=True
        )
        worker.start()

    def preprocess_worker(self, rows: list[dict[str, str]], sentinel_resolution: str, cloud_mask: bool) -> None:
        def progress(message: str) -> None:
            self.after(0, self.status_var.set, message)
            self.after(0, self._update_progress_dialog, message)
        try:
            result = preprocess_rows(
                rows,
                sentinel_resolution=sentinel_resolution,
                cloud_mask=cloud_mask,
                progress=progress,
            )
        except Exception as exc:
            self.after(0, self.preprocess_finished, None, exc)
            return
        self.after(0, self.preprocess_finished, result, None)

    def preprocess_finished(self, result: PreprocessResult | None, error: Exception | None) -> None:
        self._close_progress_dialog()
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
        self.refresh_preprocess_runs(select_path=result.run_dir)
        self.load_processing_results_for_paths([result.run_dir])
        messagebox.showinfo(
            "Preprocessing complete",
            f"Rasters written: {result.raster_count}\n"
            f"Scenes processed: {result.scene_count}\n\n"
            f"Run folder:\n{result.run_dir}\n\n"
            f"Manifest:\n{result.output_manifest}\n\n"
            f"Log:\n{result.log_file}",
        )

    def refresh_preprocess_runs(self, select_path: Path | None = None) -> None:
        if not hasattr(self, "runs_tree"):
            return
        self.runs_tree.delete(*self.runs_tree.get_children())
        for run in list_preprocess_runs():
            path = Path(run["path"])
            self.runs_tree.insert(
                "",
                "end",
                iid=str(path),
                values=(run["name"], run["raster_count"], run["modified"]),
            )
        if select_path is not None:
            iid = str(select_path)
            if self.runs_tree.exists(iid):
                self.runs_tree.selection_set(iid)
                self.runs_tree.focus(iid)
                self.runs_tree.see(iid)

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
        if not messagebox.askyesno("Delete preprocessing runs?", prompt):
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
