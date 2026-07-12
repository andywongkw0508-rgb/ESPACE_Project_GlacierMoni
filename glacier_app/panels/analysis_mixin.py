from __future__ import annotations

import datetime as dt
import queue
import threading
from fractions import Fraction
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..bands import check_scene_bands
from ..config import DEFAULT_PREVIEW_SCENE_ID
from ..glacier_retreat import GlacierRetreatResult, compare_glacier_retreat
from ..indexes import IndexResult, calculate_run_indexes
from ..masks import default_threshold_for
from ..preview import PreviewController
from ..results import (
    IndexMetricSummary,
    ProcessingOutput,
    boundary_overlay_png,
    chlorophyll_overlay_png,
    dashboard_static_preview_png,
    index_metric_summary,
    list_processing_outputs,
    overlay_coordinate_region,
    processing_preview_png,
    turbidity_overlay_png,
)
from ..sea_level import SEA_LEVEL_OUTPUT_DIR, SeaLevelImportResult, import_copernicus_sea_level
from ..sea_temperature import (
    LandsatTemperatureScene,
    RemoteTemperatureResult,
    create_remote_temperature_map,
)
from ..validation_results import (
    ValidationCardResult,
    load_validation_dashboard_results,
)
from .constants import _C_APP_BG, _C_BORDER, _C_CARD, _C_MUTED, _C_TEXT, _UI_FONT


def parse_iso_datetime(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def format_time_gap(minutes: float) -> str:
    if minutes < 120.0:
        return f"{minutes:.1f} minutes"
    if minutes < 2_880.0:
        return f"{minutes / 60.0:.1f} hours"
    return f"{minutes / 1_440.0:.1f} days"


class AnalysisMixin:
    def calculate_selected_indexes(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before calculating indexes.")
            return
        self._prefer_chlorophyll_result = False
        self._prefer_processing_result_label = None
        self._set_index_buttons_state("disabled")
        init_msg = f"Calculating spectral indexes for {len(run_paths)} run(s)..."
        self.status_var.set(init_msg)
        self._open_progress_dialog("Calculating Indexes", init_msg)
        worker = threading.Thread(target=self.index_worker, args=(run_paths,), daemon=True)
        worker.start()

    def calculate_selected_chlorophyll_map(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before building a chlorophyll-a map.")
            return
        self._prefer_chlorophyll_result = True
        self._prefer_processing_result_label = "CHL_A"
        self.result_filter_var.set("Index")
        self._set_index_buttons_state("disabled")
        init_msg = f"Building chlorophyll-a map outputs for {len(run_paths)} run(s)..."
        self.status_var.set(init_msg)
        self._open_progress_dialog("Building Chlorophyll-a Maps", init_msg)
        worker = threading.Thread(target=self.index_worker, args=(run_paths, ["CHL_A"]), daemon=True)
        worker.start()

    def calculate_selected_turbidity_warning(self) -> None:
        run_paths = self.selected_preprocess_run_paths()
        if not run_paths:
            self.status_var.set("Select one or more preprocessing runs before building a turbidity map.")
            return
        self._prefer_chlorophyll_result = False
        self._prefer_processing_result_label = "TURBIDITY"
        self.result_filter_var.set("Index")
        self._set_index_buttons_state("disabled")
        index_names = ["CHL_A", "NDTI", "TURBIDITY", "CHL_TURBIDITY_WARNING"]
        init_msg = f"Building turbidity map outputs for {len(run_paths)} run(s)..."
        self.status_var.set(init_msg)
        self._open_progress_dialog("Building Turbidity Maps", init_msg)
        worker = threading.Thread(target=self.index_worker, args=(run_paths, index_names), daemon=True)
        worker.start()

    def _set_index_buttons_state(self, state: str) -> None:
        self.index_button.configure(state=state)
        if hasattr(self, "chlorophyll_button"):
            self.chlorophyll_button.configure(state=state)
        if hasattr(self, "turbidity_button"):
            self.turbidity_button.configure(state=state)

    def _set_chlorophyll_overlay_state(self, state: str) -> None:
        if hasattr(self, "chlorophyll_overlay_button"):
            self.chlorophyll_overlay_button.configure(state=state)

    def _set_turbidity_overlay_state(self, state: str) -> None:
        if hasattr(self, "turbidity_overlay_button"):
            self.turbidity_overlay_button.configure(state=state)

    def _set_sea_level_state(self, state: str) -> None:
        if hasattr(self, "sea_level_button"):
            self.sea_level_button.configure(state=state)

    def _set_sea_temperature_state(self, state: str) -> None:
        if hasattr(self, "sea_temperature_button"):
            self.sea_temperature_button.configure(state=state)

    def _set_glacier_retreat_state(self, state: str) -> None:
        if hasattr(self, "glacier_retreat_button"):
            self.glacier_retreat_button.configure(state=state)

    def compare_glacier_retreat_boundaries(self) -> None:
        boundaries = [output for output in self.current_processing_outputs if output.kind == "Boundary"]
        if len(boundaries) < 2:
            self.status_var.set("Load at least two boundary results before comparing glacier retreat.")
            messagebox.showinfo(
                "Glacier retreat",
                "Load boundary results from at least two dates before comparing glacier retreat.",
            )
            return
        selected = self.selected_processing_output()
        preferred = selected if selected is not None and selected.kind == "Boundary" else None
        self._set_glacier_retreat_state("disabled")
        init_msg = "Comparing oldest and latest glacier boundaries..."
        self.status_var.set(init_msg)
        self._open_progress_dialog("Glacier Retreat", init_msg)
        worker = threading.Thread(
            target=self._glacier_retreat_worker,
            args=(boundaries, preferred),
            daemon=True,
        )
        worker.start()

    def _glacier_retreat_worker(
        self,
        boundaries: list[ProcessingOutput],
        preferred: ProcessingOutput | None,
    ) -> None:
        try:
            result = compare_glacier_retreat(boundaries, preferred)
        except Exception as exc:
            self.after(0, self._glacier_retreat_finished, None, exc)
            return
        self.after(0, self._glacier_retreat_finished, result, None)

    def _glacier_retreat_finished(
        self,
        result: GlacierRetreatResult | None,
        error: Exception | None,
    ) -> None:
        self._close_progress_dialog()
        self._set_glacier_retreat_state("normal")
        if error is not None:
            self.status_var.set(f"Glacier retreat comparison failed: {error}")
            messagebox.showerror("Glacier retreat failed", str(error))
            return
        if result is None:
            return
        change_label = "reduced" if result.is_retreat else "increased"
        change_value = abs(result.area_change_km2)
        percent_text = f"{result.percent_reduced:.2f}%" if result.percent_reduced is not None else "n/a"
        self.mask_stats_var.set(
            f"Glacier area {change_label}: {change_value:.3f} km2 | reduced {percent_text}"
        )
        self.status_var.set(f"Glacier retreat report saved: {result.report_file}")
        self.show_details_text(result.summary_text())
        messagebox.showinfo(
            "Glacier retreat comparison",
            f"Older area ({result.older.date}): {result.older_mask.area_km2:.3f} km2\n"
            f"Latest area ({result.newer.date}): {result.newer_mask.area_km2:.3f} km2\n"
            f"Area {change_label}: {change_value:.3f} km2\n"
            f"Percent reduced: {percent_text}\n\n"
            f"Report:\n{result.report_file}",
        )

    def import_sea_level_from_copernicus(self) -> None:
        initial_dir = SEA_LEVEL_OUTPUT_DIR if SEA_LEVEL_OUTPUT_DIR.exists() else Path.cwd()
        selected_file = filedialog.askopenfilename(
            parent=self,
            title="Select Sea-Level NetCDF File",
            initialdir=str(initial_dir),
            filetypes=(
                ("NetCDF files", "*.nc"),
                ("All files", "*.*"),
            ),
        )
        if not selected_file:
            self.status_var.set("Sea-level import cancelled.")
            return
        data_file = Path(selected_file)
        self._set_sea_level_state("disabled")
        init_msg = f"Generating sea-level dashboard PNG from {data_file.name}..."
        self.status_var.set(init_msg)
        self._open_progress_dialog("Import Sea Level", init_msg)
        worker = threading.Thread(target=self._sea_level_import_worker, args=(data_file,), daemon=True)
        worker.start()

    def _sea_level_import_worker(self, data_file: Path) -> None:
        def progress(message: str) -> None:
            self.after(0, self.status_var.set, message)
            self.after(0, self._update_progress_dialog, message)

        try:
            result = import_copernicus_sea_level(data_file=data_file, progress=progress)
        except Exception as exc:
            self.after(0, self._sea_level_import_finished, None, exc)
            return
        self.after(0, self._sea_level_import_finished, result, None)

    def _sea_level_import_finished(
        self,
        result: SeaLevelImportResult | None,
        error: Exception | None,
    ) -> None:
        self._close_progress_dialog()
        self._set_sea_level_state("normal")
        if error is not None:
            self.status_var.set(f"Sea-level import failed: {error}")
            messagebox.showerror("Sea-level import failed", str(error))
            return
        if result is None:
            return

        self.current_sea_level_result = result
        trend_text = (
            f"{result.trend_mm_per_year:.1f} mm/yr"
            if result.trend_mm_per_year is not None
            else "n/a"
        )
        self.mask_stats_var.set(f"Sea level mean {result.mean_m:.3f} m | trend {trend_text}")
        action = "Downloaded" if result.downloaded else "Loaded"
        self.status_var.set(f"{action} sea-level data and generated dashboard PNG: {result.figure_file}")
        self.refresh_open_dashboards()

    def sea_level_details(self, result: SeaLevelImportResult) -> str:
        trend_text = (
            f"{result.trend_mm_per_year:.2f} mm/year"
            if result.trend_mm_per_year is not None
            else "not available"
        )
        return (
            "Copernicus sea-level import\n"
            f"Source: Global Ocean Physics Reanalysis\n"
            f"Variable: zos, sea surface height above geoid\n"
            f"Period: {result.first_date} to {result.last_date}\n"
            f"Records: {result.record_count:,}\n"
            f"Mean: {result.mean_m:.4f} m\n"
            f"Minimum: {result.min_m:.4f} m\n"
            f"Maximum: {result.max_m:.4f} m\n"
            f"Trend: {trend_text}\n"
            f"Data file: {result.data_file}\n"
            f"Figure: {result.figure_file}"
        )

    def create_remote_sensing_temperature_map(self) -> None:
        candidates = self.remote_temperature_scene_candidates()
        if not candidates:
            message = (
                "No Landsat scene has all local blue, green, red, NIR, SWIR, and QA bands "
                "plus a Planetary Computer thermal item URL."
            )
            self.status_var.set(message)
            messagebox.showinfo("Surface temperature", message)
            return

        primary = candidates[0]
        self._set_sea_temperature_state("disabled")
        init_msg = (
            f"Matched {primary.scene_id} to {primary.matched_sentinel_scene_id} "
            f"({format_time_gap(primary.time_gap_minutes)} apart)."
        )
        self.status_var.set(init_msg)
        self._open_progress_dialog(
            "Sea and Glacier Temperature",
            init_msg,
            modal=False,
        )
        self._temperature_result_queue = queue.Queue()
        self._temperature_worker_active = True
        self.update_open_dashboard_temperature(
            message=(
                "Temperature processing in progress.\n"
                "This panel will refresh automatically."
            )
        )
        self.ensure_temperature_result_poller()
        worker = threading.Thread(
            target=self._remote_temperature_worker,
            args=(candidates[:4],),
            daemon=True,
        )
        worker.start()

    def remote_temperature_scene_candidates(self) -> list[LandsatTemperatureScene]:
        anchor, sentinel_scene_id, sentinel_datetime = self.remote_temperature_anchor()
        candidates: list[LandsatTemperatureScene] = []
        required_labels = {"blue", "green", "red", "nir08", "swir16", "qa pixel"}

        for row in self.rows:
            if row.get("sensor", "") != "landsat-c2-l2":
                continue
            item_url = str(row.get("planetary_computer_item", "")).strip()
            if not item_url:
                continue
            matched = {
                str(check.get("label", "")).strip().lower(): Path(str(check["matched_path"]))
                for check in check_scene_bands(row)
                if check.get("matched_path")
            }
            if not required_labels.issubset(matched) or not all(
                matched[label].exists() for label in required_labels
            ):
                continue
            try:
                cloud_cover = float(row.get("cloud_value", row.get("cloud_cover", 100.0)))
            except (TypeError, ValueError):
                cloud_cover = 100.0
            acquisition_datetime = str(row.get("datetime", "")) or str(row.get("date", ""))
            acquisition = parse_iso_datetime(acquisition_datetime)
            time_gap_minutes = (
                abs((acquisition - anchor).total_seconds()) / 60.0
                if acquisition is not None and anchor is not None
                else 1_000_000_000.0
            )
            candidates.append(
                LandsatTemperatureScene(
                    scene_id=str(row.get("item_id", "")),
                    date=str(row.get("date", "")),
                    acquisition_datetime=acquisition_datetime,
                    platform=str(row.get("platform", "Landsat")),
                    cloud_cover=cloud_cover,
                    planetary_computer_item=item_url,
                    matched_sentinel_scene_id=sentinel_scene_id,
                    matched_sentinel_datetime=sentinel_datetime,
                    time_gap_minutes=time_gap_minutes,
                    blue_file=matched["blue"],
                    green_file=matched["green"],
                    red_file=matched["red"],
                    nir_file=matched["nir08"],
                    swir_file=matched["swir16"],
                    qa_file=matched["qa pixel"],
                )
            )

        def rank(scene: LandsatTemperatureScene) -> tuple[float, int, float, float]:
            acquisition = parse_iso_datetime(scene.acquisition_datetime)
            tier_rank = 0 if scene.scene_id.upper().endswith("_T1") else 1
            recency_rank = -acquisition.timestamp() if acquisition is not None else 0.0
            return scene.time_gap_minutes, tier_rank, scene.cloud_cover, recency_rank

        candidates.sort(key=rank)
        return candidates

    def remote_temperature_anchor(self) -> tuple[dt.datetime | None, str, str]:
        try:
            selected = self.selected_processing_output()
        except Exception:
            selected = None

        rows: list[dict[str, str]] = []
        if selected is not None and selected.sensor == "sentinel-2-l2a":
            selected_row = next(
                (row for row in self.rows if row.get("item_id", "") == selected.scene_id),
                None,
            )
            if selected_row is not None:
                rows.append(selected_row)
            else:
                rows.append(
                    {
                        "item_id": selected.scene_id,
                        "datetime": selected.date,
                        "date": selected.date,
                    }
                )
        if (
            self.current_scene_row is not None
            and self.current_scene_row.get("sensor", "") == "sentinel-2-l2a"
        ):
            rows.append(self.current_scene_row)
        default_row = next(
            (row for row in self.rows if row.get("item_id", "") == DEFAULT_PREVIEW_SCENE_ID),
            None,
        )
        if default_row is not None:
            rows.append(default_row)

        seen: set[str] = set()
        for row in rows:
            scene_id = str(row.get("item_id", ""))
            if scene_id in seen:
                continue
            seen.add(scene_id)
            raw_datetime = str(row.get("datetime", "")) or str(row.get("date", ""))
            parsed = parse_iso_datetime(raw_datetime)
            if parsed is not None:
                return parsed, scene_id, raw_datetime
        return None, "selected Sentinel scene", ""

    def _remote_temperature_worker(self, candidates: list[LandsatTemperatureScene]) -> None:
        failures: list[str] = []

        def progress(message: str) -> None:
            self._temperature_result_queue.put(("progress", message, None))

        for index, scene in enumerate(candidates, start=1):
            progress(
                f"Trying Landsat thermal scene {index}/{len(candidates)}: "
                f"{scene.date} ({scene.cloud_cover:.1f}% cloud)..."
            )
            try:
                result = create_remote_temperature_map(scene, progress=progress)
            except Exception as exc:
                failures.append(f"{scene.scene_id}: {exc}")
                continue
            try:
                dashboard_preview = dashboard_static_preview_png(result.figure_file)
            except Exception:
                dashboard_preview = None
            self._temperature_result_queue.put(
                ("complete", (result, dashboard_preview), None)
            )
            return

        detail = "\n".join(failures)
        error = RuntimeError(
            "No nearby Landsat scene produced usable cloud-free sea and glacier temperature pixels."
            + (f"\n\n{detail}" if detail else "")
        )
        self._temperature_result_queue.put(("complete", None, error))

    def ensure_temperature_result_poller(self) -> None:
        if getattr(self, "_temperature_poll_job", None) is None:
            self._temperature_poll_job = self.after(80, self.poll_temperature_results)

    def poll_temperature_results(self) -> None:
        self._temperature_poll_job = None
        result_queue = getattr(self, "_temperature_result_queue", None)
        if result_queue is None:
            return
        while True:
            try:
                event, payload, error = result_queue.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                message = str(payload)
                self.status_var.set(message)
                self._update_progress_dialog(message)
                continue
            self._temperature_worker_active = False
            result = None
            dashboard_preview = None
            if isinstance(payload, tuple) and len(payload) == 2:
                candidate_result, candidate_preview = payload
                if isinstance(candidate_result, RemoteTemperatureResult):
                    result = candidate_result
                if isinstance(candidate_preview, Path):
                    dashboard_preview = candidate_preview
            elif isinstance(payload, RemoteTemperatureResult):
                result = payload
            self._sea_temperature_finished(result, error, dashboard_preview)
        if getattr(self, "_temperature_worker_active", False):
            try:
                self._temperature_poll_job = self.after(80, self.poll_temperature_results)
            except tk.TclError:
                self._temperature_poll_job = None

    def _sea_temperature_finished(
        self,
        result: RemoteTemperatureResult | None,
        error: Exception | None,
        dashboard_preview: Path | None = None,
    ) -> None:
        self._close_progress_dialog()
        self._set_sea_temperature_state("normal")
        if error is not None:
            self.status_var.set(f"Remote-sensing temperature map failed: {error}")
            self.update_open_dashboard_temperature(
                message=f"Temperature map failed:\n{error}"
            )
            messagebox.showerror(
                "Surface-temperature map failed",
                str(error),
                parent=self,
            )
            return
        if result is None:
            return

        self.current_sea_temperature_result = result
        self.mask_stats_var.set(
            f"Sea {result.sea.mean_c:.1f} deg C | glacier "
            f"{result.glacier.mean_c:.1f} deg C"
        )
        self.status_var.set(f"Remote-sensing temperature map saved: {result.figure_file}")
        if self.preview is not None:
            self.preview.show_image(
                str(result.figure_file),
                preserve_view=False,
                coordinate_source=result.temperature_raster,
                coordinate_region=overlay_coordinate_region(result.figure_file),
            )
            self.preview_tabs.select(1)
        self.show_details_text(result.details_text())
        if dashboard_preview is not None:
            self.update_open_dashboard_temperature(preview_path=dashboard_preview)
        else:
            self.update_open_dashboard_temperature(
                message=(
                    "Temperature map created.\n"
                    "Press Refresh to load its dashboard preview."
                )
            )

    def index_worker(self, run_paths: list[Path], index_names: list[str] | None = None) -> None:
        def progress(message: str) -> None:
            self.after(0, self.status_var.set, message)
            self.after(0, self._update_progress_dialog, message)

        results = []
        failures = []
        for run_path in run_paths:
            try:
                result = calculate_run_indexes(run_path, progress=progress, index_names=index_names)
            except Exception as exc:
                failures.append((run_path, exc))
            else:
                results.append(result)
        self.after(0, self.index_finished, results, failures)

    def index_finished(self, results: list[IndexResult], failures: list[tuple[Path, Exception]]) -> None:
        self._close_progress_dialog()
        self._set_index_buttons_state("normal")
        self.refresh_preprocess_runs()
        index_count = sum(result.index_count for result in results)
        scene_count = sum(result.scene_count for result in results)
        if failures:
            details = "\n".join(f"{path.name}: {exc}" for path, exc in failures)
            self.status_var.set(f"Created {index_count} index raster(s); {len(failures)} run(s) failed.")
            self._prefer_processing_result_label = None
            self._prefer_chlorophyll_result = False
            messagebox.showerror("Index calculation failed", details)
            return
        if not results:
            self.status_var.set("No indexes were calculated.")
            self._prefer_processing_result_label = None
            self._prefer_chlorophyll_result = False
            return
        manifest_lines = "\n".join(str(result.output_manifest) for result in results[:3])
        if len(results) > 3:
            manifest_lines = f"{manifest_lines}\n...and {len(results) - 3} more"
        self.status_var.set(f"Created {index_count} index raster(s) from {scene_count} scene(s).")
        self.load_processing_results_for_paths([result.run_dir for result in results])
        preferred_label = getattr(self, "_prefer_processing_result_label", None)
        if not preferred_label and getattr(self, "_prefer_chlorophyll_result", False):
            preferred_label = "CHL_A"
        selected_preferred = False
        if preferred_label:
            selected_preferred = self.select_first_processing_result(preferred_label)
            self._prefer_processing_result_label = None
            self._prefer_chlorophyll_result = False
        if preferred_label == "TURBIDITY" and selected_preferred:
            self.overlay_selected_turbidity_map()
            return
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

    def select_first_processing_result(self, label: str) -> bool:
        for index, output in enumerate(self._displayed_outputs):
            if output.label.upper() != label.upper():
                continue
            iid = str(index)
            self.result_tree.selection_set(iid)
            self.result_tree.focus(iid)
            self.result_tree.see(iid)
            self.on_processing_result_selected(tk.Event())
            return True
        if label.upper() == "CHL_TURBIDITY_WARNING":
            hint = "Check that red, green, and SCL/QA or NIR bands were preprocessed."
        elif label.upper() == "TURBIDITY":
            hint = "Check that red, green, and NIR or SCL/QA bands were preprocessed."
        elif label.upper() == "CHL_A":
            hint = "Check that blue, green, and SCL/QA or NIR bands were preprocessed."
        else:
            hint = "Check that the required bands were preprocessed."
        self.status_var.set(f"No {label} result was created. {hint}")
        return False

    def refresh_processing_results(self, selected_output: Path | None = None) -> None:
        selected_filter = self.result_filter_var.get()
        self._displayed_outputs = [
            output for output in self.current_processing_outputs
            if selected_filter == "All" or output.kind == selected_filter
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

    def selected_chlorophyll_output(self) -> ProcessingOutput | None:
        selected = self.selected_processing_output()
        if selected and selected.kind == "Index" and selected.label.upper() == "CHL_A":
            return selected
        if selected:
            for output in self.current_processing_outputs:
                if (
                    output.kind == "Index"
                    and output.label.upper() == "CHL_A"
                    and output.run_name == selected.run_name
                    and output.scene_id == selected.scene_id
                ):
                    return output
        for output in self.current_processing_outputs:
            if output.kind == "Index" and output.label.upper() == "CHL_A":
                return output
        return None

    def selected_turbidity_output(self) -> ProcessingOutput | None:
        selected = self.selected_processing_output()
        if selected and selected.kind == "Index" and selected.label.upper() == "TURBIDITY":
            return selected
        if selected:
            for output in self.current_processing_outputs:
                if (
                    output.kind == "Index"
                    and output.label.upper() == "TURBIDITY"
                    and output.run_name == selected.run_name
                    and output.scene_id == selected.scene_id
                ):
                    return output
        for output in self.current_processing_outputs:
            if output.kind == "Index" and output.label.upper() == "TURBIDITY":
                return output
        return None

    def matching_result_base(self, result: ProcessingOutput) -> ProcessingOutput | None:
        candidates = [
            output for output in self.current_processing_outputs
            if (
                output.kind == "Preprocessed"
                and output.run_name == result.run_name
                and output.scene_id == result.scene_id
            )
        ]
        if not candidates:
            return None

        preferred = [
            "visual",
            "red b04",
            "green b03",
            "blue b02",
            "nir b08",
            "swir b11",
        ]
        for label in preferred:
            for output in candidates:
                if output.label.strip().lower() == label:
                    return output
        return candidates[0]

    def matching_chlorophyll_base(self, chlorophyll: ProcessingOutput) -> ProcessingOutput | None:
        return self.matching_result_base(chlorophyll)

    def overlay_selected_chlorophyll_map(self) -> None:
        chlorophyll = self.selected_chlorophyll_output()
        if chlorophyll is None:
            self.status_var.set("Load or select a CHL_A result before building an overlay.")
            return
        base = self.matching_chlorophyll_base(chlorophyll)
        if base is None:
            self.status_var.set("No matching preprocessed base image was found for this CHL_A result.")
            return

        self._preview_request_id += 1
        request_id = self._preview_request_id
        self._set_chlorophyll_overlay_state("disabled")
        self.preview.show_message(f"Rendering CHL_A overlay on {base.label}...")
        self.status_var.set(f"Building CHL_A overlay for {chlorophyll.scene_id}.")
        worker = threading.Thread(
            target=self._chlorophyll_overlay_worker,
            args=(request_id, chlorophyll, base),
            daemon=True,
        )
        worker.start()

    def _chlorophyll_overlay_worker(
        self,
        request_id: int,
        chlorophyll: ProcessingOutput,
        base: ProcessingOutput,
    ) -> None:
        try:
            overlay_path = chlorophyll_overlay_png(chlorophyll, base, publish_output=True)
        except Exception as exc:
            self.after(0, self._chlorophyll_overlay_ready, request_id, chlorophyll, base, None, exc)
            return
        self.after(0, self._chlorophyll_overlay_ready, request_id, chlorophyll, base, overlay_path, None)

    def _chlorophyll_overlay_ready(
        self,
        request_id: int,
        chlorophyll: ProcessingOutput,
        base: ProcessingOutput,
        overlay_path: Path | None,
        error: Exception | None,
    ) -> None:
        self._set_chlorophyll_overlay_state("normal")
        if request_id != self._preview_request_id:
            return
        if error is not None:
            self.status_var.set(f"CHL_A overlay failed: {error}")
            self.preview.show_message("Could not render CHL_A overlay.")
            return
        if overlay_path is None:
            return
        self.preview.show_image(
            str(overlay_path),
            preserve_view=False,
            coordinate_source=chlorophyll.output_file,
            coordinate_region=overlay_coordinate_region(overlay_path),
        )
        self.preview_tabs.select(1)
        base_file = base.source_file or base.output_file
        self.show_details_text(
            "Chlorophyll-a overlay\n"
            f"Scene ID: {chlorophyll.scene_id}\n"
            f"Base image: {base.label}\n"
            f"Base file: {base_file}\n"
            f"CHL_A raster: {chlorophyll.output_file}\n"
            f"Overlay output: {overlay_path}"
        )
        self.status_var.set(f"CHL_A overlay saved: {overlay_path}")

    def overlay_selected_turbidity_map(self) -> None:
        turbidity = self.selected_turbidity_output()
        if turbidity is None:
            self.status_var.set("Load or select a TURBIDITY result before building an overlay.")
            return
        base = self.matching_result_base(turbidity)
        if base is None:
            self.status_var.set("No matching preprocessed base image was found for this TURBIDITY result.")
            return

        self._preview_request_id += 1
        request_id = self._preview_request_id
        self._set_turbidity_overlay_state("disabled")
        self.preview.show_message(f"Rendering TURBIDITY overlay on {base.label}...")
        self.status_var.set(f"Building TURBIDITY overlay for {turbidity.scene_id}.")
        worker = threading.Thread(
            target=self._turbidity_overlay_worker,
            args=(request_id, turbidity, base),
            daemon=True,
        )
        worker.start()

    def _turbidity_overlay_worker(
        self,
        request_id: int,
        turbidity: ProcessingOutput,
        base: ProcessingOutput,
    ) -> None:
        try:
            overlay_path = turbidity_overlay_png(turbidity, base, publish_output=True)
        except Exception as exc:
            self.after(0, self._turbidity_overlay_ready, request_id, turbidity, base, None, exc)
            return
        self.after(0, self._turbidity_overlay_ready, request_id, turbidity, base, overlay_path, None)

    def _turbidity_overlay_ready(
        self,
        request_id: int,
        turbidity: ProcessingOutput,
        base: ProcessingOutput,
        overlay_path: Path | None,
        error: Exception | None,
    ) -> None:
        self._set_turbidity_overlay_state("normal")
        if request_id != self._preview_request_id:
            return
        if error is not None:
            self.status_var.set(f"TURBIDITY overlay failed: {error}")
            self.preview.show_message("Could not render TURBIDITY overlay.")
            return
        if overlay_path is None:
            return
        self.preview.show_image(
            str(overlay_path),
            preserve_view=False,
            coordinate_source=turbidity.output_file,
            coordinate_region=overlay_coordinate_region(overlay_path),
        )
        self.preview_tabs.select(1)
        base_file = base.source_file or base.output_file
        self.show_details_text(
            "Turbidity overlay\n"
            f"Scene ID: {turbidity.scene_id}\n"
            f"Base image: {base.label}\n"
            f"Base file: {base_file}\n"
            f"TURBIDITY raster: {turbidity.output_file}\n"
            f"Overlay output: {overlay_path}"
        )
        self.status_var.set(f"TURBIDITY overlay saved: {overlay_path}")

    def on_processing_result_selected(self, _event: tk.Event) -> None:
        output = self.selected_processing_output()
        if output is None:
            return
        default_threshold = default_threshold_for(output)
        if default_threshold is not None:
            self.mask_threshold_var.set(f"{default_threshold:.2f}")
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self.preview.show_message(f"Rendering {output.label} preview...")
        self.show_details_text(self.processing_result_details(output))
        self.status_var.set(f"Preparing {output.kind.lower()} preview: {output.label}")
        worker = threading.Thread(
            target=self._processing_preview_worker,
            args=(request_id, output),
            daemon=True,
        )
        worker.start()

    def _processing_preview_worker(self, request_id: int, output: ProcessingOutput) -> None:
        try:
            preview_path = processing_preview_png(output)
        except Exception as exc:
            self.after(0, self._processing_preview_ready, request_id, output, None, exc)
            return
        self.after(0, self._processing_preview_ready, request_id, output, preview_path, None)

    def _processing_preview_ready(
        self,
        request_id: int,
        output: ProcessingOutput,
        preview_path: Path | None,
        error: Exception | None,
    ) -> None:
        if request_id != self._preview_request_id:
            return
        if error is not None:
            self.status_var.set(str(error))
            self.preview.show_message(f"Could not render {output.label} preview.")
            return
        if preview_path is None:
            return
        self.preview.show_image(
            str(preview_path),
            preserve_view=False,
            coordinate_source=output.output_file,
            coordinate_region=overlay_coordinate_region(preview_path),
        )
        self.status_var.set(f"Showing {output.kind.lower()} result: {output.label}")

    def open_dashboard(self) -> None:
        for existing in list(getattr(self, "_dashboard_windows", [])):
            if not self.dashboard_window_exists(existing):
                continue
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            self.refresh_dashboard(existing)
            return

        window = tk.Toplevel(self)
        try:
            window.title("Glacier Monitoring Dashboard")
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            dashboard_width = min(1380, max(1060, screen_width - 40))
            dashboard_height = min(820, max(640, screen_height - 80))
            dashboard_x = max(0, (screen_width - dashboard_width) // 2)
            dashboard_y = max(0, (screen_height - dashboard_height) // 2)
            window.geometry(
                f"{dashboard_width}x{dashboard_height}+{dashboard_x}+{dashboard_y}"
            )
            window.minsize(
                min(1060, dashboard_width),
                min(640, dashboard_height),
            )
            window.configure(bg=_C_APP_BG)
            window._dashboard_cards = {}
            window._validation_cards = {}
            window._dashboard_request_id = 0
            self.register_dashboard_window(window)
            window.protocol("WM_DELETE_WINDOW", lambda: self.close_dashboard(window))

            shell = ttk.Frame(window, padding=(16, 14), style="TFrame")
            shell.pack(fill="both", expand=True)
            shell.columnconfigure(0, weight=1)
            shell.rowconfigure(1, weight=1)

            header = ttk.Frame(shell, style="TFrame")
            header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            header.columnconfigure(0, weight=1)
            ttk.Label(
                header,
                text="Glacier Monitoring Dashboard",
                style="AppTitle.TLabel",
            ).grid(row=0, column=0, sticky="w")
            ttk.Label(
                header,
                text="Southeast Vatnajokull | Sentinel-2 and Landsat",
                style="AppSub.TLabel",
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))
            ttk.Button(header, text="Refresh", command=lambda: self.refresh_dashboard(window)).grid(
                row=0, column=1, rowspan=2, sticky="e"
            )

            pages = ttk.Notebook(shell)
            pages.grid(row=1, column=0, sticky="nsew")
            window._dashboard_notebook = pages

            body = ttk.Frame(pages, style="TFrame")
            validation_body = ttk.Frame(pages, style="TFrame")
            pages.add(body, text="Overview")
            pages.add(validation_body, text="Validation")

            for column in range(3):
                body.columnconfigure(column, weight=1, uniform="dashboard_columns")
            body.rowconfigure(0, weight=5)
            body.rowconfigure(1, weight=3)

            window._dashboard_cards["chl"] = self.build_dashboard_image_card(
                body,
                0,
                0,
                "Chlorophyll-a Map",
                None,
                show_coordinates=False,
                canvas_height=355,
            )
            window._dashboard_cards["turbidity"] = self.build_dashboard_image_card(
                body,
                0,
                1,
                "Turbidity Map",
                None,
                show_coordinates=False,
                canvas_height=355,
            )
            window._dashboard_cards["boundary"] = self.build_dashboard_image_card(
                body,
                0,
                2,
                "Glacier Boundary",
                None,
                show_coordinates=False,
                canvas_height=355,
            )
            window._dashboard_cards["index_metrics"] = self.build_dashboard_index_metrics_card(
                body,
                1,
                0,
            )
            window._dashboard_cards["sea_level"] = self.build_dashboard_image_card(
                body,
                1,
                1,
                "Sea Level",
                None,
                show_coordinates=False,
                canvas_height=245,
            )
            window._dashboard_cards["temperature"] = self.build_dashboard_image_card(
                body,
                1,
                2,
                "Sea / Glacier Temperature",
                None,
                show_coordinates=False,
                canvas_height=245,
            )

            for column in range(2):
                validation_body.columnconfigure(
                    column,
                    weight=1,
                    uniform="validation_columns",
                )
            for row in range(2):
                validation_body.rowconfigure(row, weight=1, uniform="validation_rows")

            validation_specs = (
                ("boundary_validation", 0, 0, "Glacier Boundary Validation"),
                ("chl_copernicus_validation", 0, 1, "CHL-A vs Copernicus"),
                ("chl_hls_validation", 1, 0, "CHL-A vs HLS S30"),
                ("turbidity_validation", 1, 1, "Turbidity vs Copernicus BBP"),
            )
            for key, row, column, title in validation_specs:
                window._validation_cards[key] = self.build_dashboard_validation_card(
                    validation_body,
                    row,
                    column,
                    title,
                )

            self.refresh_dashboard(window)
            window.lift()
            window.focus_force()
        except Exception as exc:
            self.unregister_dashboard_reference(window)
            try:
                window.destroy()
            except tk.TclError:
                pass
            self.status_var.set(f"Dashboard could not open: {exc}")
            messagebox.showerror("Dashboard failed", str(exc))

    def build_dashboard_validation_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
    ) -> dict[str, object]:
        card = tk.Frame(
            parent,
            bg=_C_CARD,
            highlightthickness=1,
            highlightbackground=_C_BORDER,
        )
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        header = tk.Frame(card, bg=_C_CARD)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        header.columnconfigure(0, weight=1)
        title_label = tk.Label(
            header,
            text=title,
            bg=_C_CARD,
            fg=_C_TEXT,
            font=(_UI_FONT, 10, "bold"),
            anchor="w",
        )
        title_label.grid(row=0, column=0, sticky="w")
        status_label = tk.Label(
            header,
            text="Loading...",
            bg=_C_CARD,
            fg=_C_MUTED,
            font=(_UI_FONT, 8, "bold"),
            anchor="e",
        )
        status_label.grid(row=0, column=1, sticky="e", padx=(8, 4))
        zoom_label = ttk.Label(header, text="", style="Card.Muted.TLabel")
        zoom_label.grid(row=0, column=2, sticky="e", padx=(4, 0))

        canvas = tk.Canvas(
            card,
            bg="#eef2f3",
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            width=460,
            height=155,
            cursor="fleur",
        )
        canvas.grid(row=1, column=0, sticky="nsew", padx=10)
        preview = PreviewController(
            canvas,
            zoom_label,
            show_coordinates=False,
            zoom_levels=(10, 15, 20, 25, 33, 50, 67, 100, 150, 200),
        )
        zoom_out_button = ttk.Button(
            header,
            text="-",
            width=3,
            command=lambda: preview.zoom_by(-1),
        )
        zoom_out_button.grid(row=0, column=3, sticky="e", padx=(4, 0))
        zoom_in_button = ttk.Button(
            header,
            text="+",
            width=3,
            command=lambda: preview.zoom_by(1),
        )
        zoom_in_button.grid(row=0, column=4, sticky="e", padx=(3, 0))
        fit_button = ttk.Button(header, text="Fit", width=4, command=preview.fit)
        fit_button.grid(row=0, column=5, sticky="e", padx=(3, 0))
        canvas.bind("<ButtonPress-1>", preview.start_pan)
        canvas.bind("<B1-Motion>", preview.move_pan)
        canvas.bind("<MouseWheel>", preview.mousewheel)
        canvas.bind(
            "<Button-4>",
            lambda _event, validation_preview=preview: validation_preview.zoom_by(1),
        )
        canvas.bind(
            "<Button-5>",
            lambda _event, validation_preview=preview: validation_preview.zoom_by(-1),
        )
        canvas.bind(
            "<Configure>",
            lambda _event, validation_preview=preview: validation_preview.on_canvas_configure(),
        )

        metrics_frame = tk.Frame(card, bg=_C_CARD)
        metrics_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(7, 3))
        metric_slots: list[dict[str, tk.Label]] = []
        for index in range(4):
            metrics_frame.columnconfigure(index, weight=1, uniform="validation_metrics")
            metric = tk.Frame(metrics_frame, bg=_C_CARD)
            metric.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            value_label = tk.Label(
                metric,
                text="--",
                bg=_C_CARD,
                fg=_C_TEXT,
                font=(_UI_FONT, 10, "bold"),
                anchor="w",
            )
            value_label.pack(anchor="w")
            name_label = tk.Label(
                metric,
                text="Metric",
                bg=_C_CARD,
                fg=_C_MUTED,
                font=(_UI_FONT, 8),
                anchor="w",
            )
            name_label.pack(anchor="w")
            metric_slots.append({"value": value_label, "label": name_label})

        note_label = tk.Label(
            card,
            text="Loading validation report...",
            bg=_C_CARD,
            fg=_C_MUTED,
            font=(_UI_FONT, 8),
            justify="left",
            anchor="nw",
            wraplength=440,
            height=2,
        )
        note_label.grid(row=3, column=0, sticky="ew", padx=10, pady=(1, 7))

        result = {
            "frame": card,
            "canvas": canvas,
            "title": title,
            "title_label": title_label,
            "status": status_label,
            "preview": preview,
            "zoom_label": zoom_label,
            "zoom_out_button": zoom_out_button,
            "zoom_in_button": zoom_in_button,
            "fit_button": fit_button,
            "metric_slots": metric_slots,
            "note": note_label,
        }
        self.set_dashboard_validation_card_loading(result)
        return result

    def show_dashboard_validation_loading(self, window: tk.Toplevel) -> None:
        for card in getattr(window, "_validation_cards", {}).values():
            self.set_dashboard_validation_card_loading(card)

    def set_dashboard_validation_card_loading(self, card: dict[str, object]) -> None:
        status = card.get("status")
        if isinstance(status, tk.Label):
            status.configure(text="Loading...", fg=_C_MUTED)
        note = card.get("note")
        if isinstance(note, tk.Label):
            note.configure(text="Reading the latest validation report...")
        slots = card.get("metric_slots", [])
        if isinstance(slots, list):
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                value = slot.get("value")
                label = slot.get("label")
                if isinstance(value, tk.Label):
                    value.configure(text="--")
                if isinstance(label, tk.Label):
                    label.configure(text="Metric")
        self.dashboard_show_message(card, "Loading validation plot...")

    def update_dashboard_validation_card(
        self,
        card: dict[str, object],
        result: ValidationCardResult | None,
        preview_path: Path | None,
        error: Exception | None,
    ) -> None:
        status = card.get("status")
        note = card.get("note")
        if result is None:
            if isinstance(status, tk.Label):
                status.configure(text="Unavailable", fg="#a34b3f")
            if isinstance(note, tk.Label):
                note.configure(text="The validation report could not be loaded.")
            self.dashboard_show_message(card, f"Validation failed:\n{error}" if error else "No validation result")
            return

        tone_colors = {
            "good": "#2f7d58",
            "caution": "#a56821",
            "weak": "#b04d40",
            "neutral": "#3f6fa5",
            "pending": _C_MUTED,
        }
        if isinstance(status, tk.Label):
            status.configure(
                text=result.status,
                fg=tone_colors.get(result.status_tone, _C_MUTED),
            )
        if isinstance(note, tk.Label):
            note.configure(text=result.note)

        slots = card.get("metric_slots", [])
        if isinstance(slots, list):
            for index, slot in enumerate(slots):
                if not isinstance(slot, dict):
                    continue
                metric = result.metrics[index] if index < len(result.metrics) else None
                value = slot.get("value")
                label = slot.get("label")
                if isinstance(value, tk.Label):
                    value.configure(text=metric.value if metric is not None else "--")
                if isinstance(label, tk.Label):
                    label.configure(text=metric.label if metric is not None else "Metric")

        if error is not None:
            self.dashboard_show_message(card, f"Plot unavailable:\n{error}")
        elif preview_path is not None:
            self.dashboard_show_path(card, preview_path)
        else:
            self.dashboard_show_message(card, "No validation plot available")

    def build_dashboard_index_metrics_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
    ) -> dict[str, object]:
        card = tk.Frame(
            parent,
            bg=_C_CARD,
            highlightthickness=1,
            highlightbackground=_C_BORDER,
        )
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        header = tk.Frame(card, bg=_C_CARD)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(9, 5))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Index Metrics",
            bg=_C_CARD,
            fg=_C_TEXT,
            font=(_UI_FONT, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        status = tk.Label(
            header,
            text="Loading...",
            bg=_C_CARD,
            fg=_C_MUTED,
            font=(_UI_FONT, 8),
            anchor="e",
        )
        status.grid(row=0, column=1, sticky="e")

        rows_frame = tk.Frame(card, bg=_C_CARD)
        rows_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        rows_frame.columnconfigure(0, weight=1)
        rows: dict[str, dict[str, object]] = {}
        specs = (
            ("ndsi", "NDSI", "#168c96"),
            ("ndwi", "NDWI", "#3f6fa5"),
            ("ndti", "NDTI", "#b07837"),
            ("chl", "CHL-A", "#4f7d57"),
            ("turbidity", "Turbidity", "#b45f4b"),
        )
        for index, (key, label, color) in enumerate(specs):
            metric = tk.Frame(rows_frame, bg=_C_CARD)
            metric.grid(row=index, column=0, sticky="ew", pady=2)
            metric.columnconfigure(2, weight=1)
            tk.Frame(metric, bg=color, width=4, height=28).grid(
                row=0,
                column=0,
                rowspan=2,
                sticky="ns",
                padx=(0, 7),
            )
            tk.Label(
                metric,
                text=label,
                bg=_C_CARD,
                fg=_C_TEXT,
                font=(_UI_FONT, 9, "bold"),
                width=9,
                anchor="w",
            ).grid(row=0, column=1, sticky="w")
            value = tk.Label(
                metric,
                text="--",
                bg=_C_CARD,
                fg=_C_TEXT,
                font=(_UI_FONT, 9, "bold"),
                anchor="e",
            )
            value.grid(row=0, column=3, sticky="e")
            bar = tk.Canvas(
                metric,
                width=110,
                height=7,
                bg="#e5eaec",
                highlightthickness=0,
            )
            bar.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))
            detail = tk.Label(
                metric,
                text="No data",
                bg=_C_CARD,
                fg=_C_MUTED,
                font=(_UI_FONT, 8),
                anchor="e",
            )
            detail.grid(row=1, column=3, sticky="e", padx=(8, 0))
            rows[key] = {
                "value": value,
                "detail": detail,
                "bar": bar,
                "color": color,
            }

        result = {"frame": card, "status": status, "rows": rows}
        self.show_dashboard_index_metrics_loading(result)
        return result

    def show_dashboard_index_metrics_loading(self, card: dict[str, object]) -> None:
        status = card.get("status")
        if isinstance(status, tk.Label):
            status.configure(text="Calculating...")
        rows = card.get("rows", {})
        if not isinstance(rows, dict):
            return
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            detail = row.get("detail")
            bar = row.get("bar")
            if isinstance(value, tk.Label):
                value.configure(text="--")
            if isinstance(detail, tk.Label):
                detail.configure(text="Loading")
            if isinstance(bar, tk.Canvas):
                bar.delete("all")

    def update_dashboard_index_metrics(
        self,
        card: dict[str, object],
        summaries: dict[str, tuple[IndexMetricSummary | None, Exception | None]],
    ) -> None:
        rows = card.get("rows", {})
        if not isinstance(rows, dict):
            return
        available = 0
        for key, row in rows.items():
            if not isinstance(row, dict):
                continue
            summary, error = summaries.get(key, (None, None))
            value = row.get("value")
            detail = row.get("detail")
            bar = row.get("bar")
            if summary is None or error is not None:
                if isinstance(value, tk.Label):
                    value.configure(text="--")
                if isinstance(detail, tk.Label):
                    detail.configure(text="Unavailable")
                if isinstance(bar, tk.Canvas):
                    self.draw_dashboard_metric_bar(bar, 0.0, "#9aa7ac")
                continue
            available += 1
            value_text, detail_text, fraction = self.format_dashboard_index_metric(key, summary)
            if isinstance(value, tk.Label):
                value.configure(text=value_text)
            if isinstance(detail, tk.Label):
                detail.configure(text=detail_text)
            if isinstance(bar, tk.Canvas):
                self.draw_dashboard_metric_bar(bar, fraction, str(row.get("color", _C_MUTED)))
        status = card.get("status")
        if isinstance(status, tk.Label):
            status.configure(text=f"{available}/5 available")

    def format_dashboard_index_metric(
        self,
        key: str,
        summary: IndexMetricSummary,
    ) -> tuple[str, str, float]:
        if key == "ndsi":
            fraction = summary.fraction_above_threshold or 0.0
            return f"{summary.mean:+.3f}", f"Ice {fraction * 100:.1f}%", fraction
        if key == "ndwi":
            fraction = summary.fraction_above_threshold or 0.0
            return f"{summary.mean:+.3f}", f"Water {fraction * 100:.1f}%", fraction
        if key == "ndti":
            fraction = max(0.0, min(1.0, (summary.mean + 1.0) / 2.0))
            return (
                f"{summary.mean:+.3f}",
                f"P10 {summary.percentile_10:+.2f}",
                fraction,
            )
        if key == "chl":
            denominator = max(summary.percentile_90, 1e-6)
            fraction = max(0.0, min(1.0, summary.median / denominator))
            return f"{summary.median:.2f}", "Median mg/m3", fraction
        fraction = max(0.0, min(1.0, summary.mean))
        high_fraction = summary.fraction_above_threshold or 0.0
        return f"{summary.mean:.3f}", f"High {high_fraction * 100:.1f}%", fraction

    def draw_dashboard_metric_bar(self, canvas: tk.Canvas, fraction: float, color: str) -> None:
        width = max(1, int(float(canvas.cget("width"))))
        height = max(1, int(float(canvas.cget("height"))))
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#e5eaec", outline="")
        fill_width = int(round(width * max(0.0, min(1.0, fraction))))
        if fill_width > 0:
            canvas.create_rectangle(0, 0, fill_width, height, fill=color, outline="")

    def register_dashboard_window(self, window: tk.Toplevel) -> None:
        if not hasattr(self, "_dashboard_windows"):
            self._dashboard_windows = []
        self._dashboard_windows.append(window)
        window.bind(
            "<Destroy>",
            lambda event, target=window: self.unregister_dashboard_window(event, target),
            add="+",
        )

    def dashboard_window_exists(self, window: tk.Toplevel) -> bool:
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            return False

    def close_dashboard(self, window: tk.Toplevel) -> None:
        if hasattr(window, "_dashboard_request_id"):
            window._dashboard_request_id += 1
        self.unregister_dashboard_reference(window)
        try:
            window.destroy()
        except tk.TclError:
            pass

    def unregister_dashboard_reference(self, window: tk.Toplevel) -> None:
        if not hasattr(self, "_dashboard_windows"):
            return
        self._dashboard_windows = [item for item in self._dashboard_windows if item is not window]

    def unregister_dashboard_window(self, event: tk.Event, window: tk.Toplevel) -> None:
        if event.widget is not window:
            return
        self.unregister_dashboard_reference(window)

    def refresh_open_dashboards(self) -> None:
        if not hasattr(self, "_dashboard_windows"):
            return
        live_windows = []
        for window in self._dashboard_windows:
            if not self.dashboard_window_exists(window):
                continue
            live_windows.append(window)
            self.refresh_dashboard(window)
        self._dashboard_windows = live_windows

    def update_open_dashboard_temperature(
        self,
        *,
        preview_path: Path | None = None,
        message: str | None = None,
    ) -> None:
        if not hasattr(self, "_dashboard_windows"):
            return
        live_windows = []
        for window in self._dashboard_windows:
            if not self.dashboard_window_exists(window):
                continue
            live_windows.append(window)
            card = window._dashboard_cards.get("temperature")
            if not card:
                continue
            if preview_path is not None:
                self.dashboard_show_path(card, preview_path)
            elif message is not None:
                self.dashboard_show_message(card, message)
        self._dashboard_windows = live_windows

    def refresh_dashboard(self, window: tk.Toplevel) -> None:
        if not self.dashboard_window_exists(window):
            return
        temperature_active = getattr(self, "_temperature_worker_active", False)
        targets = self.dashboard_outputs()
        static_targets = self.dashboard_static_targets(window)
        if temperature_active:
            static_targets.pop("temperature", None)
            temperature_card = window._dashboard_cards.get("temperature")
            if temperature_card:
                self.dashboard_show_message(
                    temperature_card,
                    "Temperature processing in progress.\n"
                    "This panel will refresh automatically.",
                )
        card_targets = {
            key: targets[key]
            for key in ("chl", "turbidity", "boundary")
        }
        metric_targets = {
            key: targets[key]
            for key in ("ndsi", "ndwi", "ndti", "chl", "turbidity")
        }
        for key, output in card_targets.items():
            card = window._dashboard_cards.get(key)
            if not card:
                continue
            self.set_dashboard_card_loading(card, output)
        metrics_card = window._dashboard_cards.get("index_metrics")
        if metrics_card:
            self.show_dashboard_index_metrics_loading(metrics_card)
        self.show_dashboard_validation_loading(window)
        window._dashboard_request_id += 1
        request_id = window._dashboard_request_id
        self.status_var.set("Refreshing dashboard previews and validation...")
        self.ensure_dashboard_result_poller()
        self._dashboard_worker_count = getattr(self, "_dashboard_worker_count", 0) + 1
        worker = threading.Thread(
            target=self._dashboard_preview_worker,
            args=(window, request_id, card_targets, static_targets, metric_targets),
            daemon=True,
        )
        worker.start()

    def ensure_dashboard_result_poller(self) -> None:
        if not hasattr(self, "_dashboard_result_queue"):
            self._dashboard_result_queue = queue.Queue()
        if getattr(self, "_dashboard_poll_job", None) is None:
            self._dashboard_poll_job = self.after(80, self.poll_dashboard_results)

    def poll_dashboard_results(self) -> None:
        self._dashboard_poll_job = None
        result_queue = getattr(self, "_dashboard_result_queue", None)
        if result_queue is None:
            return
        while True:
            try:
                (
                    window,
                    request_id,
                    previews,
                    static_previews,
                    metric_summaries,
                    validation_results,
                    validation_previews,
                    validation_error,
                ) = result_queue.get_nowait()
            except queue.Empty:
                break
            self._dashboard_worker_count = max(
                0,
                getattr(self, "_dashboard_worker_count", 1) - 1,
            )
            self._dashboard_preview_ready(
                window,
                request_id,
                previews,
                static_previews,
                metric_summaries,
                validation_results,
                validation_previews,
                validation_error,
            )
        if getattr(self, "_dashboard_worker_count", 0) > 0:
            try:
                self._dashboard_poll_job = self.after(80, self.poll_dashboard_results)
            except tk.TclError:
                self._dashboard_poll_job = None

    def dashboard_static_targets(self, window: tk.Toplevel) -> dict[str, Path]:
        targets: dict[str, Path] = {}
        specs = (
            ("sea_level", getattr(self, "current_sea_level_result", None), "No sea-level result loaded."),
            (
                "temperature",
                getattr(self, "current_sea_temperature_result", None),
                "No sea and glacier temperature map generated.",
            ),
        )
        for key, result, empty_message in specs:
            card = window._dashboard_cards.get(key)
            if not card:
                continue
            if result is None:
                self.dashboard_show_message(card, empty_message)
                continue
            figure_file = Path(result.figure_file)
            if not figure_file.exists():
                self.dashboard_show_message(
                    card,
                    f"{card.get('title', 'Dashboard')} image is unavailable.",
                )
                continue
            self.dashboard_show_message(card, "Rendering preview...")
            targets[key] = figure_file
        return targets

    def build_dashboard_static_image_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        empty_message: str,
        canvas_height: int = 300,
    ) -> dict[str, object]:
        card = ttk.Frame(
            parent,
            padding=10,
            style="Card.TFrame",
            borderwidth=1,
            relief="solid",
        )
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        ttk.Label(card, text=title, style="Card.TLabel", font=(_UI_FONT, 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        canvas = tk.Canvas(
            card,
            bg="#eef2f3",
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            width=410,
            height=canvas_height,
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        result = {
            "frame": card,
            "canvas": canvas,
            "title": title,
            "image_path": None,
            "photo": None,
            "source_photo": None,
            "loaded_path": None,
            "resize_job": None,
            "message": "",
            "empty_message": empty_message,
        }
        canvas.bind(
            "<Configure>",
            lambda _event, dashboard_card=result: self.schedule_dashboard_static_redraw(
                dashboard_card
            ),
        )
        self.dashboard_show_static_message(result, empty_message)
        return result

    def dashboard_show_static_message(self, card: dict[str, object], text: str) -> None:
        canvas = card["canvas"]
        if not isinstance(canvas, tk.Canvas):
            return
        card["image_path"] = None
        card["photo"] = None
        card["source_photo"] = None
        card["loaded_path"] = None
        card["message"] = text
        self.dashboard_redraw_static_card(card)

    def dashboard_redraw_static_message(self, card: dict[str, object]) -> None:
        canvas = card["canvas"]
        if not isinstance(canvas, tk.Canvas):
            return
        text = str(card.get("message", ""))
        canvas.delete("all")
        canvas.create_text(
            max(1, canvas.winfo_width()) // 2,
            max(1, canvas.winfo_height()) // 2,
            text=text,
            fill="#617078",
            width=max(160, canvas.winfo_width() - 24),
            justify="center",
        )

    def dashboard_show_static_image(self, card: dict[str, object], image_path: Path) -> None:
        if str(card.get("loaded_path", "")) != str(image_path):
            card["source_photo"] = None
            card["loaded_path"] = None
        card["image_path"] = image_path
        card["message"] = ""
        self.dashboard_redraw_static_card(card)

    def schedule_dashboard_static_redraw(self, card: dict[str, object]) -> None:
        canvas = card.get("canvas")
        if not isinstance(canvas, tk.Canvas):
            return
        resize_job = card.get("resize_job")
        if resize_job is not None:
            try:
                canvas.after_cancel(str(resize_job))
            except tk.TclError:
                pass
        card["resize_job"] = canvas.after(
            80,
            lambda dashboard_card=card: self.dashboard_redraw_static_card(dashboard_card),
        )

    def dashboard_redraw_static_card(self, card: dict[str, object]) -> None:
        card["resize_job"] = None
        if card.get("image_path"):
            self.dashboard_redraw_static_image(card)
        else:
            self.dashboard_redraw_static_message(card)

    def dashboard_redraw_static_image(self, card: dict[str, object]) -> None:
        image_path = card.get("image_path")
        canvas = card.get("canvas")
        if not image_path or not isinstance(canvas, tk.Canvas):
            return
        path = Path(str(image_path))
        if not path.exists():
            card["image_path"] = None
            card["message"] = f"{card.get('title', 'Dashboard')} image is not available."
            self.dashboard_redraw_static_message(card)
            return
        max_w = max(1, canvas.winfo_width() - 12)
        max_h = max(1, canvas.winfo_height() - 12)
        if max_w <= 2 or max_h <= 2:
            self.schedule_dashboard_static_redraw(card)
            return
        image = card.get("source_photo")
        if not isinstance(image, tk.PhotoImage) or str(card.get("loaded_path", "")) != str(path):
            image = tk.PhotoImage(file=str(path))
            card["source_photo"] = image
            card["loaded_path"] = path
        fit_scale = min(1.0, max_w / image.width(), max_h / image.height())
        ratio = Fraction(fit_scale).limit_denominator(8)
        if ratio.numerator == 0:
            ratio = Fraction(1, 8)
        display = image.copy()
        if ratio.numerator > 1:
            display = display.zoom(ratio.numerator)
        if ratio.denominator > 1:
            display = display.subsample(ratio.denominator)
        card["photo"] = display
        canvas.delete("all")
        canvas.create_image(
            max(1, canvas.winfo_width()) // 2,
            max(1, canvas.winfo_height()) // 2,
            image=display,
            anchor="center",
        )

    def build_dashboard_image_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        output: ProcessingOutput | None,
        show_coordinates: bool = True,
        canvas_height: int = 340,
    ) -> dict[str, object]:
        card = ttk.Frame(
            parent,
            padding=10,
            style="Card.TFrame",
            borderwidth=1,
            relief="solid",
        )
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        header = ttk.Frame(card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=title, style="Card.TLabel", font=(_UI_FONT, 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        zoom_label = ttk.Label(header, text="", style="Card.Muted.TLabel")
        zoom_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        canvas = tk.Canvas(
            card,
            bg="#eef2f3",
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            width=410,
            height=canvas_height,
            cursor="fleur",
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        preview = PreviewController(
            canvas,
            zoom_label,
            show_coordinates=show_coordinates,
            zoom_levels=(10, 15, 20, 25, 33, 50, 67, 100, 150, 200),
        )
        zoom_out_button = ttk.Button(header, text="-", width=3, command=lambda: preview.zoom_by(-1))
        zoom_out_button.grid(row=0, column=2, sticky="e", padx=(5, 0))
        zoom_in_button = ttk.Button(header, text="+", width=3, command=lambda: preview.zoom_by(1))
        zoom_in_button.grid(row=0, column=3, sticky="e", padx=(3, 0))
        fit_button = ttk.Button(header, text="Fit", width=4, command=preview.fit)
        fit_button.grid(row=0, column=4, sticky="e", padx=(3, 0))
        canvas.bind("<ButtonPress-1>", preview.start_pan)
        canvas.bind("<B1-Motion>", preview.move_pan)
        canvas.bind("<MouseWheel>", preview.mousewheel)
        canvas.bind("<Button-4>", lambda _event, dashboard_preview=preview: dashboard_preview.zoom_by(1))
        canvas.bind("<Button-5>", lambda _event, dashboard_preview=preview: dashboard_preview.zoom_by(-1))
        canvas.bind("<Configure>", lambda _event, dashboard_preview=preview: dashboard_preview.on_canvas_configure())
        result = {
            "frame": card,
            "canvas": canvas,
            "title": title,
            "preview": preview,
            "zoom_label": zoom_label,
            "zoom_out_button": zoom_out_button,
            "zoom_in_button": zoom_in_button,
            "fit_button": fit_button,
        }
        self.set_dashboard_card_loading(result, output)
        return result

    def build_dashboard_info_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        text: str,
    ) -> ttk.Label:
        card = ttk.Frame(parent, padding=10, style="Card.TFrame")
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="Card.TLabel", font=(_UI_FONT, 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        label = ttk.Label(
            card,
            text=text,
            style="Card.TLabel",
            wraplength=460,
            justify="left",
        )
        label.grid(row=1, column=0, sticky="nw")
        return label

    def set_dashboard_card_loading(
        self,
        card: dict[str, object],
        output: ProcessingOutput | None,
    ) -> None:
        preview = card.get("preview")
        zoom_label = card.get("zoom_label")
        if isinstance(zoom_label, ttk.Label):
            zoom_label.configure(text="")
        if not isinstance(preview, PreviewController):
            self.dashboard_show_static_message(
                card,
                "Rendering preview..." if output is not None else "No matching result loaded.",
            )
            return
        if output is None:
            preview.show_message("No result loaded")
            return
        preview.show_message("Rendering preview...")

    def _dashboard_preview_worker(
        self,
        window: tk.Toplevel,
        request_id: int,
        targets: dict[str, ProcessingOutput | None],
        static_targets: dict[str, Path],
        metric_targets: dict[str, ProcessingOutput | None],
    ) -> None:
        previews: dict[str, tuple[ProcessingOutput | None, Path | None, Exception | None]] = {}
        for key, output in targets.items():
            if output is None:
                previews[key] = (None, None, None)
                continue
            try:
                source_preview = self.dashboard_preview_path(key, output)
                previews[key] = (
                    output,
                    dashboard_static_preview_png(source_preview),
                    None,
                )
            except Exception as exc:
                previews[key] = (output, None, exc)
        static_previews: dict[str, tuple[Path | None, Exception | None]] = {}
        for key, source in static_targets.items():
            try:
                static_previews[key] = (dashboard_static_preview_png(source), None)
            except Exception as exc:
                static_previews[key] = (None, exc)
        metric_summaries: dict[
            str,
            tuple[IndexMetricSummary | None, Exception | None],
        ] = {}
        for key, output in metric_targets.items():
            if output is None:
                metric_summaries[key] = (None, None)
                continue
            try:
                metric_summaries[key] = (index_metric_summary(output), None)
            except Exception as exc:
                metric_summaries[key] = (None, exc)
        validation_results: dict[str, ValidationCardResult] = {}
        validation_previews: dict[str, tuple[Path | None, Exception | None]] = {}
        validation_error: Exception | None = None
        try:
            validation_results = load_validation_dashboard_results()
            for key, result in validation_results.items():
                if result.image_file is None:
                    validation_previews[key] = (None, None)
                    continue
                try:
                    validation_previews[key] = (
                        dashboard_static_preview_png(result.image_file),
                        None,
                    )
                except Exception as exc:
                    validation_previews[key] = (None, exc)
        except Exception as exc:
            validation_error = exc
        self._dashboard_result_queue.put(
            (
                window,
                request_id,
                previews,
                static_previews,
                metric_summaries,
                validation_results,
                validation_previews,
                validation_error,
            )
        )

    def dashboard_preview_path(self, key: str, output: ProcessingOutput) -> Path:
        if key == "chl":
            base = self.matching_result_base(output)
            if base is None:
                raise RuntimeError("No matching base image for CHL-A overlay.")
            return chlorophyll_overlay_png(output, base)
        if key == "turbidity":
            base = self.matching_result_base(output)
            if base is None:
                raise RuntimeError("No matching base image for turbidity overlay.")
            return turbidity_overlay_png(output, base)
        if key == "boundary":
            base = self.matching_result_base(output)
            if base is None:
                raise RuntimeError("No matching base image for boundary overlay.")
            return boundary_overlay_png(output, base)
        return processing_preview_png(output)

    def _dashboard_preview_ready(
        self,
        window: tk.Toplevel,
        request_id: int,
        previews: dict[str, tuple[ProcessingOutput | None, Path | None, Exception | None]],
        static_previews: dict[str, tuple[Path | None, Exception | None]],
        metric_summaries: dict[str, tuple[IndexMetricSummary | None, Exception | None]],
        validation_results: dict[str, ValidationCardResult],
        validation_previews: dict[str, tuple[Path | None, Exception | None]],
        validation_error: Exception | None,
    ) -> None:
        if not self.dashboard_window_exists(window):
            return
        if request_id != getattr(window, "_dashboard_request_id", None):
            return
        try:
            for key, (output, preview_path, error) in previews.items():
                card = window._dashboard_cards.get(key)
                if not card:
                    continue
                if error is not None:
                    self.dashboard_show_message(card, f"Preview failed:\n{error}")
                    continue
                if output is None or preview_path is None:
                    self.dashboard_show_message(card, "No matching result loaded")
                    continue
                self.dashboard_show_image(card, output, preview_path)
            for key, (preview_path, error) in static_previews.items():
                card = window._dashboard_cards.get(key)
                if not card:
                    continue
                if error is not None:
                    self.dashboard_show_message(card, f"Preview failed:\n{error}")
                    continue
                if preview_path is not None:
                    self.dashboard_show_path(card, preview_path)
            metrics_card = window._dashboard_cards.get("index_metrics")
            if metrics_card:
                self.update_dashboard_index_metrics(metrics_card, metric_summaries)
            for key, card in getattr(window, "_validation_cards", {}).items():
                preview_path, preview_error = validation_previews.get(key, (None, None))
                self.update_dashboard_validation_card(
                    card,
                    validation_results.get(key),
                    preview_path,
                    preview_error or validation_error,
                )
            self.status_var.set("Dashboard refreshed.")
        except tk.TclError:
            return

    def dashboard_show_message(self, card: dict[str, object], text: str) -> None:
        preview = card.get("preview")
        zoom_label = card.get("zoom_label")
        if isinstance(zoom_label, ttk.Label):
            zoom_label.configure(text="")
        if isinstance(preview, PreviewController):
            preview.show_message(text)
        else:
            self.dashboard_show_static_message(card, text)

    def dashboard_show_path(self, card: dict[str, object], preview_path: Path) -> None:
        preview = card.get("preview")
        if isinstance(preview, PreviewController):
            preview.show_image(str(preview_path), preserve_view=False)
        else:
            self.dashboard_show_static_image(card, preview_path)

    def dashboard_show_image(
        self,
        card: dict[str, object],
        output: ProcessingOutput,
        preview_path: Path,
    ) -> None:
        preview = card.get("preview")
        if not isinstance(preview, PreviewController):
            self.dashboard_show_static_image(card, preview_path)
            return
        preview.show_image(
            str(preview_path),
            preserve_view=False,
            coordinate_source=output.output_file,
            coordinate_region=overlay_coordinate_region(preview_path),
        )

    def dashboard_outputs(self) -> dict[str, ProcessingOutput | None]:
        anchor = self.dashboard_anchor_output()
        return {
            "ndsi": self.find_dashboard_output("Index", "NDSI", anchor),
            "ndwi": self.find_dashboard_output("Index", "NDWI", anchor),
            "ndti": self.find_dashboard_output("Index", "NDTI", anchor),
            "chl": self.find_dashboard_output("Index", "CHL_A", anchor),
            "turbidity": self.find_dashboard_output("Index", "TURBIDITY", anchor),
            "warning": self.find_dashboard_output(
                "Index", "CHL_TURBIDITY_WARNING", anchor
            ),
            "boundary": self.find_dashboard_output("Boundary", None, anchor),
        }

    def dashboard_anchor_output(self) -> ProcessingOutput | None:
        try:
            return self.selected_processing_output()
        except Exception:
            return None

    def find_dashboard_output(
        self,
        kind: str,
        label: str | None,
        anchor: ProcessingOutput | None,
    ) -> ProcessingOutput | None:
        candidates = [
            output for output in self.current_processing_outputs
            if (
                output.kind == kind
                and (label is None or output.label.upper() == label.upper())
                and (kind != "Boundary" or "NDSI" in output.label.upper())
            )
        ]
        if not candidates:
            return None
        if anchor is not None:
            for output in candidates:
                if output.run_name == anchor.run_name and output.scene_id == anchor.scene_id:
                    return output
            for output in candidates:
                if output.scene_id == anchor.scene_id:
                    return output
            for output in candidates:
                if output.run_name == anchor.run_name:
                    return output
        return candidates[0]

    def dashboard_output_summary(self, output: ProcessingOutput) -> str:
        parts = [
            f"Run: {output.run_name}",
            f"Scene: {output.scene_id}",
            f"Date: {output.date}",
            f"File: {output.output_file.name}",
        ]
        if output.kind == "Boundary":
            if output.area_km2:
                parts.append(f"Boundary length: {output.area_km2:.3f} km")
            if output.pixel_count:
                parts.append(f"Boundary pixels: {output.pixel_count:,}")
        elif output.formula:
            parts.append(f"Formula: {output.formula}")
        return "\n".join(parts)

    def dashboard_index_summary(self, targets: dict[str, ProcessingOutput | None]) -> str:
        index_count = sum(1 for output in self.current_processing_outputs if output.kind == "Index")
        mask_count = sum(1 for output in self.current_processing_outputs if output.kind == "Mask")
        boundary_count = sum(1 for output in self.current_processing_outputs if output.kind == "Boundary")
        sea_level = getattr(self, "current_sea_level_result", None)
        sea_level_text = (
            f"{sea_level.first_date} to {sea_level.last_date}"
            if sea_level is not None
            else "missing"
        )
        sea_temperature = getattr(self, "current_sea_temperature_result", None)
        sea_stats = getattr(sea_temperature, "sea", None)
        glacier_stats = getattr(sea_temperature, "glacier", None)
        if sea_stats is not None and glacier_stats is not None:
            sea_temperature_text = (
                f"sea {sea_stats.mean_c:.1f}, glacier {glacier_stats.mean_c:.1f} deg C"
            )
        elif sea_temperature is not None:
            sea_temperature_text = "map available"
        else:
            sea_temperature_text = "missing"
        selected = [
            value.label if value is not None else "missing"
            for value in (
                targets["ndsi"],
                targets["ndwi"],
                targets["ndti"],
                targets["chl"],
                targets["turbidity"],
                targets["warning"],
                targets["boundary"],
            )
        ]
        return (
            f"Loaded indexes: {index_count}\n"
            f"Loaded masks: {mask_count}\n"
            f"Loaded boundaries: {boundary_count}\n"
            f"Sea level: {sea_level_text}\n"
            f"Surface temperature: {sea_temperature_text}\n"
            f"Dashboard panels: {', '.join(selected)}"
        )

    def dashboard_notes(self, targets: dict[str, ProcessingOutput | None]) -> str:
        missing = [
            label
            for key, label in (
                ("ndsi", "NDSI"),
                ("ndwi", "NDWI"),
                ("ndti", "NDTI"),
                ("chl", "CHL_A"),
                ("turbidity", "TURBIDITY"),
                ("warning", "CHL_TURBIDITY_WARNING"),
                ("boundary", "Boundary"),
            )
            if targets.get(key) is None
        ]
        if missing:
            return "Missing: " + ", ".join(missing)
        return "All dashboard map panels have matching loaded results."

    def processing_result_details(self, output: ProcessingOutput) -> str:
        size_label = "Boundary pixels" if output.kind == "Boundary" else "Mask pixels"
        metric_label = "Boundary length" if output.kind == "Boundary" else "Area"
        metric_unit = "km" if output.kind == "Boundary" else "km2"
        fields = [
            ("Run", output.run_name),
            ("Type", output.kind),
            ("Result", output.label),
            ("Scene ID", output.scene_id),
            ("Date", output.date),
            ("Sensor", output.sensor),
            ("Formula", output.formula),
            (size_label, f"{output.pixel_count:,}" if output.pixel_count else ""),
            (metric_label, f"{output.area_km2:.3f} {metric_unit}" if output.area_km2 else ""),
            ("Output", str(output.output_file)),
        ]
        return "\n".join(f"{label}: {value}" for label, value in fields if value)
