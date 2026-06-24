from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from tkinter import ttk
from typing import Any

from osgeo import gdal, osr

from .config import PREPROCESS_TARGET_CRS


@dataclass
class RasterCoordinateMapper:
    raster_width: int
    raster_height: int
    preview_width: int
    preview_height: int
    geo_transform: tuple[float, float, float, float, float, float]
    transformer: Any | None = None
    preview_x: int = 0
    preview_y: int = 0

    @classmethod
    def from_raster(
        cls,
        raster_path: Path,
        preview_width: int,
        preview_height: int,
        preview_region: tuple[int, int, int, int] | None = None,
    ) -> RasterCoordinateMapper | None:
        if not raster_path.exists():
            return None
        if preview_region is None:
            region_x, region_y, region_width, region_height = 0, 0, preview_width, preview_height
        else:
            region_x, region_y, region_width, region_height = preview_region
        if region_width <= 0 or region_height <= 0:
            return None
        ds = gdal.Open(str(raster_path))
        if ds is None:
            return None
        geo_transform = ds.GetGeoTransform()
        projection = ds.GetProjection()
        raster_width = ds.RasterXSize
        raster_height = ds.RasterYSize
        ds = None

        if not projection:
            return None

        transformer = build_project_transform(projection)
        return cls(
            raster_width=raster_width,
            raster_height=raster_height,
            preview_width=region_width,
            preview_height=region_height,
            geo_transform=geo_transform,
            transformer=transformer,
            preview_x=region_x,
            preview_y=region_y,
        )

    def coordinate_at(self, preview_x: float, preview_y: float) -> tuple[float, float] | None:
        local_x = preview_x - self.preview_x
        local_y = preview_y - self.preview_y
        if local_x < 0 or local_y < 0 or local_x > self.preview_width or local_y > self.preview_height:
            return None
        raster_x = local_x * self.raster_width / max(1, self.preview_width)
        raster_y = local_y * self.raster_height / max(1, self.preview_height)
        gt = self.geo_transform
        x = gt[0] + raster_x * gt[1] + raster_y * gt[2]
        y = gt[3] + raster_x * gt[4] + raster_y * gt[5]
        if self.transformer is not None:
            x, y, _z = self.transformer.TransformPoint(float(x), float(y))
        return float(x), float(y)


def build_project_transform(source_projection: str) -> Any | None:
    if not source_projection:
        return None
    source = osr.SpatialReference()
    source.ImportFromWkt(source_projection)
    target = osr.SpatialReference()
    target.SetFromUserInput(PREPROCESS_TARGET_CRS)
    if hasattr(osr, "OAMS_TRADITIONAL_GIS_ORDER"):
        source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if source.IsSame(target):
        return None
    return osr.CoordinateTransformation(source, target)


class PreviewController:
    def __init__(self, canvas: tk.Canvas, zoom_label: ttk.Label) -> None:
        self.canvas = canvas
        self.zoom_label = zoom_label
        self.original_image: tk.PhotoImage | None = None
        self.preview_image: tk.PhotoImage | None = None
        self.canvas_image_id: int | None = None
        self.zoom = 100
        self._resample_cache: dict[int, tk.PhotoImage] = {}
        self.coordinate_mapper: RasterCoordinateMapper | None = None
        self.coordinate_text_id: int | None = None
        self.coordinate_bg_id: int | None = None
        self.coordinate_text = self.empty_coordinate_text()
        self._pending_fit_after_layout = False
        self._auto_fit = False
        self._last_fit_size: tuple[int, int] = (0, 0)
        self.canvas.bind("<Motion>", self.update_coordinate_from_event, add="+")
        self.canvas.bind("<Leave>", lambda _event: self.set_coordinate_text(self.empty_coordinate_text()), add="+")

    def show_image(
        self,
        path_text: str,
        preserve_view: bool = False,
        coordinate_source: str | Path | list[str | Path] | tuple[str | Path, ...] | None = None,
        coordinate_region: tuple[int, int, int, int] | None = None,
    ) -> bool:
        path = Path(path_text)
        if not path.exists():
            self.original_image = None
            self.preview_image = None
            self.coordinate_mapper = None
            self._resample_cache.clear()
            self.canvas.delete("all")
            self.reset_coordinate_items()
            self.canvas.create_text(170, 130, text="Preview image is not available.", fill="#617078")
            self.set_coordinate_text(self.empty_coordinate_text())
            return False

        self.original_image = tk.PhotoImage(file=str(path))
        self.coordinate_mapper = self.build_coordinate_mapper(coordinate_source, coordinate_region)
        self.coordinate_text = self.empty_coordinate_text()
        self._resample_cache.clear()
        self._auto_fit = not preserve_view
        if preserve_view:
            self.redraw(center=False)
        else:
            self._pending_fit_after_layout = True
            self.fit()
            self.canvas.after_idle(self._finish_pending_fit)
            self.canvas.after(120, self._finish_pending_fit)
        return True

    def show_message(self, text: str) -> None:
        self.original_image = None
        self.preview_image = None
        self.coordinate_mapper = None
        self._resample_cache.clear()
        self.canvas.delete("all")
        self.reset_coordinate_items()
        self.canvas.create_text(170, 130, text=text, fill="#617078")
        self.set_coordinate_text(self.empty_coordinate_text())

    def build_coordinate_mapper(
        self,
        coordinate_source: str | Path | list[str | Path] | tuple[str | Path, ...] | None,
        coordinate_region: tuple[int, int, int, int] | None = None,
    ) -> RasterCoordinateMapper | None:
        if self.original_image is None or coordinate_source is None:
            return None
        if isinstance(coordinate_source, (str, Path)):
            candidates = [coordinate_source]
        else:
            candidates = list(coordinate_source)
        for candidate in candidates:
            if not candidate:
                continue
            try:
                mapper = RasterCoordinateMapper.from_raster(
                    Path(candidate),
                    self.original_image.width(),
                    self.original_image.height(),
                    coordinate_region,
                )
            except Exception:
                mapper = None
            if mapper is not None:
                return mapper
        return None

    def fit(self) -> None:
        if not self.original_image:
            return
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        self._auto_fit = True
        self._last_fit_size = (canvas_width, canvas_height)
        image_width = self.original_image.width()
        image_height = self.original_image.height()
        fit_percent = min(100, int(min(canvas_width / image_width, canvas_height / image_height) * 100))
        self.zoom = max(10, fit_percent)
        self.redraw(center=True)

    def _finish_pending_fit(self) -> None:
        if not self._pending_fit_after_layout or not self.original_image:
            return
        if self.canvas.winfo_width() <= 20 or self.canvas.winfo_height() <= 20:
            return
        self._pending_fit_after_layout = False
        self.fit()

    def zoom_by(self, direction: int) -> None:
        if not self.original_image:
            return
        self._auto_fit = False
        levels = [10, 15, 20, 25, 33, 50, 67, 100, 150, 200, 300, 400]
        nearest_index = min(range(len(levels)), key=lambda index: abs(levels[index] - self.zoom))
        next_index = max(0, min(len(levels) - 1, nearest_index + direction))
        self.zoom = levels[next_index]
        self.redraw(center=False)

    def redraw(self, center: bool) -> None:
        if not self.original_image:
            return
        image = self.resample(self.original_image, self.zoom)
        self.preview_image = image
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        viewport_x = self.canvas.canvasx(canvas_width // 2)
        viewport_y = self.canvas.canvasy(canvas_height // 2)
        offset_x = 0.0
        offset_y = 0.0
        if not center and self.canvas_image_id is not None:
            coords = self.canvas.coords(self.canvas_image_id)
            if len(coords) >= 2:
                offset_x = viewport_x - coords[0]
                offset_y = viewport_y - coords[1]

        self.canvas.delete("all")
        self.reset_coordinate_items()
        if center:
            x = canvas_width // 2
            y = canvas_height // 2
        else:
            x = viewport_x - offset_x
            y = viewport_y - offset_y
        self.canvas_image_id = self.canvas.create_image(x, y, image=image, anchor="center")
        bounds = self.canvas.bbox(self.canvas_image_id)
        if bounds:
            self.canvas.configure(scrollregion=bounds)
        self.zoom_label.configure(text=f"{self.zoom}%")
        self.draw_coordinate_label()

    def resample(self, image: tk.PhotoImage, zoom_percent: int) -> tk.PhotoImage:
        cached = self._resample_cache.get(zoom_percent)
        if cached is not None:
            return cached
        if zoom_percent == 100:
            scaled = image.copy()
            self._resample_cache[zoom_percent] = scaled
            return scaled
        ratio = Fraction(zoom_percent, 100).limit_denominator(8)
        scaled = image.copy()
        if ratio.numerator > 1:
            scaled = scaled.zoom(ratio.numerator)
        if ratio.denominator > 1:
            scaled = scaled.subsample(ratio.denominator)
        if len(self._resample_cache) > 8:
            self._resample_cache.clear()
        self._resample_cache[zoom_percent] = scaled
        return scaled

    def start_pan(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def move_pan(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self.position_coordinate_label()
        self.update_coordinate_from_event(event)

    def mousewheel(self, event: tk.Event) -> None:
        self.zoom_by(1 if event.delta > 0 else -1)

    def on_canvas_configure(self) -> None:
        if self._pending_fit_after_layout and self.original_image:
            self._finish_pending_fit()
        elif self._auto_fit and self.original_image:
            size = (max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
            if size != self._last_fit_size:
                self.fit()
            else:
                self.position_coordinate_label()
        elif self.canvas_image_id is None and self.original_image:
            self.fit()
        else:
            self.position_coordinate_label()

    def center_if_needed(self) -> None:
        self.on_canvas_configure()

    def empty_coordinate_text(self) -> str:
        return f"{PREPROCESS_TARGET_CRS}: --"

    def reset_coordinate_items(self) -> None:
        self.coordinate_text_id = None
        self.coordinate_bg_id = None

    def draw_coordinate_label(self) -> None:
        if self.coordinate_bg_id is None:
            self.coordinate_bg_id = self.canvas.create_rectangle(
                0,
                0,
                1,
                1,
                fill="#f4f8f9",
                outline="#d4dde1",
            )
        if self.coordinate_text_id is None:
            self.coordinate_text_id = self.canvas.create_text(
                0,
                0,
                text=self.coordinate_text,
                fill="#1f2d33",
                anchor="sw",
                font=("Segoe UI", 9),
            )
        self.position_coordinate_label()

    def position_coordinate_label(self) -> None:
        if self.coordinate_text_id is None or self.coordinate_bg_id is None:
            return
        canvas_height = max(1, self.canvas.winfo_height())
        x = self.canvas.canvasx(8)
        y = self.canvas.canvasy(canvas_height - 8)
        self.canvas.coords(self.coordinate_text_id, x, y)
        self.canvas.itemconfigure(self.coordinate_text_id, text=self.coordinate_text)
        bbox = self.canvas.bbox(self.coordinate_text_id)
        if bbox:
            pad = 4
            self.canvas.coords(
                self.coordinate_bg_id,
                bbox[0] - pad,
                bbox[1] - pad,
                bbox[2] + pad,
                bbox[3] + pad,
            )
            self.canvas.tag_raise(self.coordinate_bg_id)
            self.canvas.tag_raise(self.coordinate_text_id)

    def set_coordinate_text(self, text: str) -> None:
        self.coordinate_text = text
        self.draw_coordinate_label()

    def update_coordinate_from_event(self, event: tk.Event) -> None:
        coordinate = self.coordinate_at_canvas_point(event.x, event.y)
        if coordinate is None:
            self.set_coordinate_text(self.empty_coordinate_text())
            return
        x, y = coordinate
        self.set_coordinate_text(f"{PREPROCESS_TARGET_CRS}  E {x:.1f}  N {y:.1f}")

    def coordinate_at_canvas_point(self, event_x: int, event_y: int) -> tuple[float, float] | None:
        if (
            self.original_image is None
            or self.preview_image is None
            or self.canvas_image_id is None
            or self.coordinate_mapper is None
        ):
            return None
        coords = self.canvas.coords(self.canvas_image_id)
        if len(coords) < 2:
            return None
        canvas_x = self.canvas.canvasx(event_x)
        canvas_y = self.canvas.canvasy(event_y)
        display_width = self.preview_image.width()
        display_height = self.preview_image.height()
        left = coords[0] - display_width / 2
        top = coords[1] - display_height / 2
        display_x = canvas_x - left
        display_y = canvas_y - top
        if display_x < 0 or display_y < 0 or display_x > display_width or display_y > display_height:
            return None
        preview_x = display_x * self.original_image.width() / max(1, display_width)
        preview_y = display_y * self.original_image.height() / max(1, display_height)
        return self.coordinate_mapper.coordinate_at(preview_x, preview_y)
