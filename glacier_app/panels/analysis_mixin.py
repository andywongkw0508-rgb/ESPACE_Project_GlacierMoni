from __future__ import annotations

import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from ..indexes import IndexResult, calculate_run_indexes
from ..masks import default_threshold_for
from ..results import ProcessingOutput, list_processing_outputs, processing_preview_png


class AnalysisMixin:
    def calculate_selected_indexes(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before calculating indexes.")
            return
        self.index_button.configure(state="disabled")
        init_msg = f"Calculating NDSI and NDWI for {len(run_paths)} run(s)…"
        self.status_var.set(init_msg)
        self._open_progress_dialog("Calculating Indexes", init_msg)
        worker = threading.Thread(target=self.index_worker, args=(run_paths,), daemon=True)
        worker.start()

    def index_worker(self, run_paths: list[Path]) -> None:
        def progress(message: str) -> None:
            self.after(0, self.status_var.set, message)
            self.after(0, self._update_progress_dialog, message)
        results = []
        failures = []
        for run_path in run_paths:
            try:
                result = calculate_run_indexes(run_path, progress=progress)
            except Exception as exc:
                failures.append((run_path, exc))
            else:
                results.append(result)
        self.after(0, self.index_finished, results, failures)

    def index_finished(self, results: list[IndexResult], failures: list[tuple[Path, Exception]]) -> None:
        self._close_progress_dialog()
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

    def load_processing_results_for_paths(
        self, run_paths: list[Path], selected_output: Path | None = None
    ) -> None:
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
        self._advance_step(3)
        if outputs:
            self.status_var.set(f"Loaded {len(outputs)} processing result raster(s).")
        else:
            self.status_var.set("No processing result rasters were found for the selected run(s).")

    def refresh_processing_results(self, selected_output: Path | None = None) -> None:
        f = self.result_filter_var.get()
        self._displayed_outputs = [
            o for o in self.current_processing_outputs
            if f == "All" or o.kind == f
        ]
        self.result_tree.delete(*self.result_tree.get_children())
        selected_iid = ""
        for index, output in enumerate(self._displayed_outputs):
            iid = str(index)
            self.result_tree.insert(
                "",
                "end",
                iid=iid,
                tags=("odd",) if index % 2 == 1 else (),
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
        self._displayed_outputs = []
        self.loaded_processing_run_paths = []
        self.mask_stats_var.set("")
        if hasattr(self, "result_tree"):
            self.result_tree.delete(*self.result_tree.get_children())

    def selected_processing_output(self) -> ProcessingOutput | None:
        selection = self.result_tree.selection()
        if not selection:
            return None
        return self._displayed_outputs[int(selection[0])]

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

    def processing_result_details(self, output: ProcessingOutput) -> str:
        size_label = "Boundary pixels" if output.kind == "Boundary" else "Mask pixels"
        metric_label = "Boundary length" if output.kind == "Boundary" else "Area"
        metric_unit = "km" if output.kind == "Boundary" else "km2"
        fields = [
            ("Run",         output.run_name),
            ("Type",        output.kind),
            ("Result",      output.label),
            ("Scene ID",    output.scene_id),
            ("Date",        output.date),
            ("Sensor",      output.sensor),
            ("Formula",     output.formula),
            (size_label,    f"{output.pixel_count:,}" if output.pixel_count else ""),
            (metric_label,  f"{output.area_km2:.3f} {metric_unit}" if output.area_km2 else ""),
            ("Output",      str(output.output_file)),
        ]
        return "\n".join(f"{label}: {value}" for label, value in fields if value)
