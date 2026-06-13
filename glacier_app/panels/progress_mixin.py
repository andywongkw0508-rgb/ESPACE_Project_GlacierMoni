from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .constants import _UI_FONT


class ProgressMixin:
    def _open_progress_dialog(self, title: str, message: str = "Working…") -> None:
        if self._progress_dialog:
            self._close_progress_dialog()
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(dlg, padding=(24, 18, 24, 18))
        frame.pack(fill="both", expand=True)

        msg_var = tk.StringVar(value=message)
        ttk.Label(frame, textvariable=msg_var, font=(_UI_FONT, 10),
                  wraplength=360, style="TLabel").pack(anchor="w")

        bar = ttk.Progressbar(frame, mode="indeterminate", length=400)
        bar.pack(pady=(14, 0))
        bar.start(12)

        dlg._msg_var = msg_var  # type: ignore[attr-defined]
        dlg._bar = bar          # type: ignore[attr-defined]

        self.update_idletasks()
        px, py = self.winfo_x(), self.winfo_y()
        pw, ph = self.winfo_width(), self.winfo_height()
        dlg.update_idletasks()
        dw = dlg.winfo_reqwidth()
        dh = dlg.winfo_reqheight()
        dlg.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

        dlg.grab_set()
        self._progress_dialog = dlg

    def _update_progress_dialog(self, message: str) -> None:
        dlg = self._progress_dialog
        if dlg is None:
            return
        try:
            dlg._msg_var.set(message)  # type: ignore[attr-defined]
        except tk.TclError:
            pass

    def _close_progress_dialog(self) -> None:
        dlg = self._progress_dialog
        self._progress_dialog = None
        if dlg is None:
            return
        try:
            dlg._bar.stop()         # type: ignore[attr-defined]
            dlg.grab_release()
            dlg.destroy()
        except tk.TclError:
            pass
