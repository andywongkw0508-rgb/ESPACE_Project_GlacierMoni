from __future__ import annotations

import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from ..indexes import IndexResult, calculate_run_indexes
from ..masks import default_threshold_for
from ..preview import PreviewController
from ..results import (
    ProcessingOutput,
    boundary_overlay_png,
    chlorophyll_overlay_png,
    list_processing_outputs,
    overlay_coordinate_region,
    processing_preview_png,
    turbidity_overlay_png,
)
from .constants import _C_APP_BG, _C_BORDER, _UI_FONT


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
            overlay_path = chlorophyll_overlay_png(chlorophyll, base)
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
            f"Overlay preview: {overlay_path}"
        )
        self.status_var.set(f"Showing CHL_A overlay on {base.label}: {chlorophyll.scene_id}")

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
            overlay_path = turbidity_overlay_png(turbidity, base)
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
            f"Overlay preview: {overlay_path}"
        )
        self.status_var.set(f"Showing TURBIDITY overlay on {base.label}: {turbidity.scene_id}")

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
        window = tk.Toplevel(self)
        window.title("Glacier Monitoring Dashboard")
        window.geometry("1380x820")
        window.minsize(1060, 640)
        window.configure(bg=_C_APP_BG)
        window._dashboard_cards = {}
        window._dashboard_info_labels = {}

        shell = ttk.Frame(window, padding=14, style="TFrame")
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
            text="Loaded result overview for chlorophyll-a, turbidity, boundary detection, indexes, and temperature.",
            style="AppSub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Refresh", command=lambda: self.refresh_dashboard(window)).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        body = ttk.Frame(shell, style="TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=6)
        body.rowconfigure(1, weight=2)

        targets = self.dashboard_outputs()
        window._dashboard_cards["chl"] = self.build_dashboard_image_card(
            body, 0, 0, "Chlorophyll-a Map", targets["chl"]
        )
        window._dashboard_cards["turbidity"] = self.build_dashboard_image_card(
            body, 0, 1, "Turbidity Map", targets["turbidity"]
        )
        window._dashboard_cards["boundary"] = self.build_dashboard_image_card(
            body, 0, 2, "Boundary Detection", targets["boundary"]
        )
        window._dashboard_info_labels["index"] = self.build_dashboard_info_card(
            body,
            1,
            0,
            "Index Summary",
            self.dashboard_index_summary(targets),
        )
        window._dashboard_info_labels["temperature"] = self.build_dashboard_info_card(
            body,
            1,
            1,
            "Temperature",
            "No temperature product loaded yet.\nReserved for a sea-surface or air-temperature raster/table.",
        )
        window._dashboard_info_labels["notes"] = self.build_dashboard_info_card(
            body,
            1,
            2,
            "Notes",
            self.dashboard_notes(targets),
        )

        self.refresh_dashboard(window)

    def refresh_dashboard(self, window: tk.Toplevel) -> None:
        if not window.winfo_exists():
            return
        targets = self.dashboard_outputs()
        if hasattr(window, "_dashboard_info_labels"):
            index_label = window._dashboard_info_labels.get("index")
            notes_label = window._dashboard_info_labels.get("notes")
            if index_label is not None:
                index_label.configure(text=self.dashboard_index_summary(targets))
            if notes_label is not None:
                notes_label.configure(text=self.dashboard_notes(targets))
        card_targets = {
            "chl": targets["chl"],
            "turbidity": targets["turbidity"],
            "boundary": targets["boundary"],
        }
        for key, output in card_targets.items():
            card = window._dashboard_cards.get(key)
            if not card:
                continue
            self.set_dashboard_card_loading(card, output)
        worker = threading.Thread(
            target=self._dashboard_preview_worker,
            args=(window, card_targets),
            daemon=True,
        )
        worker.start()

    def build_dashboard_image_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        output: ProcessingOutput | None,
    ) -> dict[str, object]:
        card = ttk.Frame(parent, padding=10, style="Card.TFrame")
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
            bg="#c6d9e0",
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            width=410,
            height=410,
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        preview = PreviewController(canvas, zoom_label)
        fit_button = ttk.Button(header, text="Fit", command=preview.fit)
        fit_button.grid(row=0, column=2, sticky="e", padx=(6, 0))
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
        preview = card["preview"]
        zoom_label = card["zoom_label"]
        if isinstance(zoom_label, ttk.Label):
            zoom_label.configure(text="")
        if not isinstance(preview, PreviewController):
            return
        if output is None:
            preview.show_message("No result loaded")
            return
        preview.show_message("Rendering preview...")

    def _dashboard_preview_worker(
        self,
        window: tk.Toplevel,
        targets: dict[str, ProcessingOutput | None],
    ) -> None:
        previews: dict[str, tuple[ProcessingOutput | None, Path | None, Exception | None]] = {}
        for key, output in targets.items():
            if output is None:
                previews[key] = (None, None, None)
                continue
            try:
                previews[key] = (output, self.dashboard_preview_path(key, output), None)
            except Exception as exc:
                previews[key] = (output, None, exc)
        self.after(0, self._dashboard_preview_ready, window, previews)

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
        previews: dict[str, tuple[ProcessingOutput | None, Path | None, Exception | None]],
    ) -> None:
        if not window.winfo_exists():
            return
        for key, (output, preview_path, error) in previews.items():
            card = window._dashboard_cards.get(key)
            if not card:
                continue
            if error is not None:
                self.dashboard_show_message(card, f"Preview failed:\n{error}")
                continue
            if output is None or preview_path is None:
                self.dashboard_show_message(card, "No result loaded")
                continue
            self.dashboard_show_image(card, output, preview_path)
        self.status_var.set("Dashboard refreshed.")

    def dashboard_show_message(self, card: dict[str, object], text: str) -> None:
        preview = card["preview"]
        zoom_label = card["zoom_label"]
        if isinstance(zoom_label, ttk.Label):
            zoom_label.configure(text="")
        if isinstance(preview, PreviewController):
            preview.show_message(text)

    def dashboard_show_image(
        self,
        card: dict[str, object],
        output: ProcessingOutput,
        preview_path: Path,
    ) -> None:
        preview = card["preview"]
        if not isinstance(preview, PreviewController):
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
            "chl": self.find_dashboard_output("Index", "CHL_A", anchor),
            "turbidity": self.find_dashboard_output("Index", "TURBIDITY", anchor),
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
            if output.kind == kind and (label is None or output.label.upper() == label.upper())
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
        selected = [
            value.label if value is not None else "missing"
            for value in (targets["chl"], targets["turbidity"], targets["boundary"])
        ]
        return (
            f"Loaded indexes: {index_count}\n"
            f"Loaded masks: {mask_count}\n"
            f"Loaded boundaries: {boundary_count}\n"
            f"Dashboard panels: {', '.join(selected)}"
        )

    def dashboard_notes(self, targets: dict[str, ProcessingOutput | None]) -> str:
        missing = []
        if targets["chl"] is None:
            missing.append("CHL_A")
        if targets["turbidity"] is None:
            missing.append("TURBIDITY")
        if targets["boundary"] is None:
            missing.append("Boundary")
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
