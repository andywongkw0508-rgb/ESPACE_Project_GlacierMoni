from __future__ import annotations

import threading
from tkinter import messagebox

from ..boundaries import BoundaryResult, extract_boundary
from ..config import OVERLAY_BASE_SCENE_ID
from ..masks import MaskResult, build_mask
from ..overlays import OverlayResult, best_2026_base, best_2026_base_from_rows, build_year_boundary_overlay
from ..results import ProcessingOutput


class MaskBoundaryMixin:
    def build_selected_mask(self) -> None:
        output = self.selected_processing_output()
        if output is None:
            self.status_var.set("Select an NDSI or NDWI result before building a mask.")
            return
        try:
            threshold = float(self.mask_threshold_var.get())
        except ValueError:
            self.status_var.set("Mask threshold must be a number.")
            return
        if threshold < -1 or threshold > 1:
            self.status_var.set("Mask threshold should be between -1 and 1.")
            return
        self.mask_button.configure(state="disabled")
        self.status_var.set(f"Building {output.label} mask with threshold >= {threshold:.3f}.")
        worker = threading.Thread(target=self.mask_worker, args=(output, threshold), daemon=True)
        worker.start()

    def extract_selected_boundary(self) -> None:
        output = self.selected_processing_output()
        if output is None or output.kind != "Mask" or "NDSI" not in output.label.upper():
            self.status_var.set("Select an NDSI mask before extracting a glacier boundary.")
            return
        self.boundary_button.configure(state="disabled")
        self.status_var.set(f"Extracting refined boundary from {output.label}.")
        worker = threading.Thread(target=self.boundary_worker, args=(output,), daemon=True)
        worker.start()

    def build_all_masks(self) -> None:
        index_outputs = [o for o in self.current_processing_outputs if o.kind == "Index"]
        if not index_outputs:
            self.status_var.set("No index results loaded. Calculate indexes first.")
            return
        try:
            threshold = float(self.mask_threshold_var.get())
        except ValueError:
            self.status_var.set("Mask threshold must be a number.")
            return
        if threshold < -1 or threshold > 1:
            self.status_var.set("Mask threshold should be between -1 and 1.")
            return
        self.batch_mask_button.configure(state="disabled")
        self.mask_button.configure(state="disabled")
        init_msg = f"Building masks for {len(index_outputs)} index result(s) — threshold ≥ {threshold:.3f}"
        self.status_var.set(init_msg)
        self._open_progress_dialog("Building All Masks", init_msg)
        worker = threading.Thread(
            target=self._batch_mask_worker, args=(index_outputs, threshold), daemon=True
        )
        worker.start()

    def extract_all_boundaries(self) -> None:
        mask_outputs = [
            o for o in self.current_processing_outputs
            if o.kind == "Mask" and "NDSI" in o.label.upper()
        ]
        if not mask_outputs:
            self.status_var.set("No NDSI mask results loaded. Build NDSI masks first.")
            return
        self.batch_boundary_button.configure(state="disabled")
        self.boundary_button.configure(state="disabled")
        init_msg = f"Extracting boundaries for {len(mask_outputs)} mask(s)…"
        self.status_var.set(init_msg)
        self._open_progress_dialog("Extracting All Boundaries", init_msg)
        worker = threading.Thread(
            target=self._batch_boundary_worker, args=(mask_outputs,), daemon=True
        )
        worker.start()

    def _batch_mask_worker(self, outputs: list[ProcessingOutput], threshold: float) -> None:
        results = []
        failures = []
        for i, output in enumerate(outputs):
            msg = f"Building mask {i + 1}/{len(outputs)}: {output.label}…"
            self.after(0, self.status_var.set, msg)
            self.after(0, self._update_progress_dialog, msg)
            try:
                result = build_mask(output, threshold)
                results.append(result)
            except Exception as exc:
                failures.append((output, exc))
        self.after(0, self._batch_mask_finished, results, failures)

    def _batch_boundary_worker(self, outputs: list[ProcessingOutput]) -> None:
        results = []
        failures = []
        for i, output in enumerate(outputs):
            msg = f"Extracting boundary {i + 1}/{len(outputs)}: {output.label}…"
            self.after(0, self.status_var.set, msg)
            self.after(0, self._update_progress_dialog, msg)
            try:
                result = extract_boundary(output)
                results.append(result)
            except Exception as exc:
                failures.append((output, exc))
        self.after(0, self._batch_boundary_finished, results, failures)

    def _batch_mask_finished(
        self, results: list[MaskResult], failures: list[tuple[ProcessingOutput, Exception]]
    ) -> None:
        self._close_progress_dialog()
        self.batch_mask_button.configure(state="normal")
        self.mask_button.configure(state="normal")
        if failures:
            details = "\n".join(f"{o.label}: {exc}" for o, exc in failures)
            self.status_var.set(f"Built {len(results)} mask(s); {len(failures)} failed.")
            messagebox.showerror("Batch mask failed", details)
        if not results:
            return
        run_paths = self.loaded_processing_run_paths or list({r.run_dir for r in results})
        self.load_processing_results_for_paths(run_paths)
        total_area = sum(r.area_km2 for r in results)
        self.status_var.set(f"Built {len(results)} mask(s). Total area: {total_area:.3f} km².")
        if not failures:
            lines = "\n".join(f"  {r.output.label}: {r.area_km2:.3f} km²" for r in results[:10])
            if len(results) > 10:
                lines += f"\n  ...and {len(results) - 10} more"
            messagebox.showinfo(
                "Batch mask complete",
                f"Masks built: {len(results)}\nTotal area: {total_area:.3f} km²\n\n{lines}",
            )

    def _batch_boundary_finished(
        self, results: list[BoundaryResult], failures: list[tuple[ProcessingOutput, Exception]]
    ) -> None:
        self._close_progress_dialog()
        self.batch_boundary_button.configure(state="normal")
        self.boundary_button.configure(state="normal")
        if failures:
            details = "\n".join(f"{o.label}: {exc}" for o, exc in failures)
            self.status_var.set(f"Extracted {len(results)} boundary(ies); {len(failures)} failed.")
            messagebox.showerror("Batch boundary failed", details)
        if not results:
            return
        run_paths = self.loaded_processing_run_paths or list({r.run_dir for r in results})
        self.load_processing_results_for_paths(run_paths)
        total_length = sum(r.boundary_length_km for r in results)
        self.status_var.set(f"Extracted {len(results)} boundary(ies). Total length: {total_length:.3f} km.")
        if not failures:
            lines = "\n".join(
                f"  {r.output.label}: {r.boundary_length_km:.3f} km, {r.polygon_count} polygon(s)"
                for r in results[:10]
            )
            if len(results) > 10:
                lines += f"\n  ...and {len(results) - 10} more"
            messagebox.showinfo(
                "Batch boundary complete",
                f"Boundaries extracted: {len(results)}\nTotal length: {total_length:.3f} km\n\n{lines}",
            )

    def build_boundary_overlay(self) -> None:
        base = best_2026_base(self.current_processing_outputs) or best_2026_base_from_rows(self.rows)
        boundaries = [
            output for output in self.current_processing_outputs
            if output.kind == "Boundary" and "NDSI" in output.label.upper()
        ]
        if base is None:
            self.status_var.set(f"No target visual raster is available for overlay: {OVERLAY_BASE_SCENE_ID}")
            return
        if not boundaries:
            self.status_var.set("Extract at least one boundary before building the target-scene overlay.")
            return
        self.overlay_button.configure(state="disabled")
        self.status_var.set(f"Building year-colored overlay on target base: {base.label}.")
        worker = threading.Thread(target=self.overlay_worker, args=(base, boundaries), daemon=True)
        worker.start()

    def mask_worker(self, output: ProcessingOutput, threshold: float) -> None:
        try:
            result = build_mask(output, threshold)
        except Exception as exc:
            self.after(0, self.mask_finished, None, exc)
            return
        self.after(0, self.mask_finished, result, None)

    def boundary_worker(self, output: ProcessingOutput) -> None:
        try:
            result = extract_boundary(output)
        except Exception as exc:
            self.after(0, self.boundary_finished, None, exc)
            return
        self.after(0, self.boundary_finished, result, None)

    def overlay_worker(self, base: ProcessingOutput, boundaries: list[ProcessingOutput]) -> None:
        try:
            result = build_year_boundary_overlay(base, boundaries)
        except Exception as exc:
            self.after(0, self.overlay_finished, None, exc)
            return
        self.after(0, self.overlay_finished, result, None)

    def mask_finished(self, result: MaskResult | None, error: Exception | None) -> None:
        self.mask_button.configure(state="normal")
        if error:
            self.status_var.set(f"Mask failed: {error}")
            messagebox.showerror("Mask failed", str(error))
            return
        if result is None:
            return
        run_paths = self.loaded_processing_run_paths or [result.run_dir]
        self.load_processing_results_for_paths(run_paths, selected_output=result.output.output_file)
        stats_text = f"{result.area_km2:.3f} km2 | {result.mask_pixels:,} pixels"
        self.mask_stats_var.set(stats_text)
        self.status_var.set(f"Mask created: {stats_text}")
        messagebox.showinfo(
            "Mask complete",
            f"Mask pixels: {result.mask_pixels:,}\n"
            f"Valid pixels: {result.valid_pixels:,}\n"
            f"Water excluded: {result.water_excluded_pixels:,}\n"
            f"Cloud/QA excluded: {result.cloud_excluded_pixels:,}\n"
            f"Area: {result.area_km2:.3f} km2\n\n"
            f"Mask file:\n{result.output.output_file}\n\n"
            f"Manifest:\n{result.manifest}",
        )

    def boundary_finished(self, result: BoundaryResult | None, error: Exception | None) -> None:
        self.boundary_button.configure(state="normal")
        if error:
            self.status_var.set(f"Boundary extraction failed: {error}")
            messagebox.showerror("Boundary extraction failed", str(error))
            return
        if result is None:
            return
        run_paths = self.loaded_processing_run_paths or [result.run_dir]
        self.load_processing_results_for_paths(run_paths, selected_output=result.output.output_file)
        stats_text = f"{result.boundary_length_km:.3f} km boundary | {result.polygon_count:,} polygon(s)"
        self.mask_stats_var.set(stats_text)
        self.status_var.set(f"Boundary extracted: {stats_text}")
        messagebox.showinfo(
            "Boundary complete",
            f"Source mask pixels: {result.source_pixels:,}\n"
            f"Refined mask pixels: {result.refined_pixels:,}\n"
            f"Boundary pixels: {result.boundary_pixels:,}\n"
            f"Boundary length: {result.boundary_length_km:.3f} km\n"
            f"Polygons: {result.polygon_count:,}\n\n"
            f"Detected regions: {result.source_region_count:,}\n"
            f"Detached regions removed: {result.removed_region_count:,}\n"
            f"Dominant area share: {result.largest_region_share:.1%}\n\n"
            f"Boundary raster:\n{result.output.output_file}\n\n"
            f"Boundary GeoJSON:\n{result.boundary_file}\n\n"
            f"Polygon GeoJSON:\n{result.polygon_file}\n\n"
            f"Manifest:\n{result.manifest}",
        )

    def overlay_finished(self, result: OverlayResult | None, error: Exception | None) -> None:
        self.overlay_button.configure(state="normal")
        if error:
            self.status_var.set(f"Overlay failed: {error}")
            messagebox.showerror("Overlay failed", str(error))
            return
        if result is None:
            return
        self.preview.show_image(str(result.output_file), preserve_view=False, coordinate_source=result.base_file)
        self.preview_tabs.select(1)
        years = ", ".join(result.years)
        self.mask_stats_var.set(f"Overlay: {years}")
        self.status_var.set(f"Overlay created for {result.boundary_count} boundary result(s): {result.output_file}")
        self.show_details_text(
            "Boundary overlay\n"
            f"Years: {years}\n"
            f"Boundary results: {result.boundary_count}\n"
            f"Base raster: {result.base_file}\n"
            f"Output: {result.output_file}"
        )
