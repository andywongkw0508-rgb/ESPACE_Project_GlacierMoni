from __future__ import annotations

import tkinter as tk
from fractions import Fraction
from pathlib import Path
from tkinter import ttk


class PreviewController:
    def __init__(self, canvas: tk.Canvas, zoom_label: ttk.Label) -> None:
        self.canvas = canvas
        self.zoom_label = zoom_label
        self.original_image: tk.PhotoImage | None = None
        self.preview_image: tk.PhotoImage | None = None
        self.canvas_image_id: int | None = None
        self.zoom = 100

    def show_image(self, path_text: str, preserve_view: bool = False) -> bool:
        path = Path(path_text)
        if not path.exists():
            self.original_image = None
            self.preview_image = None
            self.canvas.delete("all")
            self.canvas.create_text(170, 130, text="Preview image is not available.", fill="#617078")
            return False

        self.original_image = tk.PhotoImage(file=str(path))
        if preserve_view:
            self.redraw(center=False)
        else:
            self.fit()
        return True

    def show_message(self, text: str) -> None:
        self.original_image = None
        self.preview_image = None
        self.canvas.delete("all")
        self.canvas.create_text(170, 130, text=text, fill="#617078")

    def fit(self) -> None:
        if not self.original_image:
            return
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        image_width = self.original_image.width()
        image_height = self.original_image.height()
        fit_percent = min(100, int(min(canvas_width / image_width, canvas_height / image_height) * 100))
        self.zoom = max(10, fit_percent)
        self.redraw(center=True)

    def zoom_by(self, direction: int) -> None:
        if not self.original_image:
            return
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

    def resample(self, image: tk.PhotoImage, zoom_percent: int) -> tk.PhotoImage:
        if zoom_percent == 100:
            return image.copy()
        ratio = Fraction(zoom_percent, 100).limit_denominator(8)
        scaled = image.copy()
        if ratio.numerator > 1:
            scaled = scaled.zoom(ratio.numerator)
        if ratio.denominator > 1:
            scaled = scaled.subsample(ratio.denominator)
        return scaled

    def start_pan(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def move_pan(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def mousewheel(self, event: tk.Event) -> None:
        self.zoom_by(1 if event.delta > 0 else -1)

    def center_if_needed(self) -> None:
        if self.canvas_image_id is None and self.original_image:
            self.fit()
