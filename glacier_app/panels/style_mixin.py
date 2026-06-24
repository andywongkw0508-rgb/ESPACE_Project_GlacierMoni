from __future__ import annotations

from tkinter import ttk

from .constants import (
    _UI_FONT,
    _C_APP_BG, _C_CARD, _C_TEXT, _C_MUTED, _C_BORDER, _C_STATUS,
    _C_SIDEBAR, _C_SIDEBAR_H, _C_SIDEBAR_T, _C_SIDEBAR_M, _C_SIDEBAR_BD, _C_SIDEBAR_F,
    _C_ACCENT, _C_ACCENT_DK,
    _C_DANGER, _C_DANGER_DK,
    _C_TREE_ALT,
)


class StyleMixin:
    def configure_style(self) -> None:
        self._ui_scale = 1.0
        self.configure(bg=_C_APP_BG)
        s = ttk.Style(self)
        s.theme_use("clam")
        self._style = s

        # frames
        s.configure("TFrame",         background=_C_APP_BG)
        s.configure("Card.TFrame",     background=_C_CARD)
        s.configure("Sidebar.TFrame",  background=_C_SIDEBAR)

        # labels
        s.configure("TLabel",               background=_C_APP_BG,  foreground=_C_TEXT,      font=(_UI_FONT, 10))
        s.configure("Card.TLabel",          background=_C_CARD,    foreground=_C_TEXT,       font=(_UI_FONT, 10))
        s.configure("Card.Muted.TLabel",    background=_C_CARD,    foreground=_C_MUTED,      font=(_UI_FONT, 9))
        s.configure("AppTitle.TLabel",      background=_C_APP_BG,  foreground="#152328",     font=(_UI_FONT, 17, "bold"))
        s.configure("AppSub.TLabel",        background=_C_APP_BG,  foreground=_C_MUTED,      font=(_UI_FONT, 10))
        s.configure("Metric.TLabel",        background=_C_SIDEBAR, foreground=_C_ACCENT,     font=(_UI_FONT, 22, "bold"))
        s.configure("Sidebar.TLabel",       background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,  font=(_UI_FONT, 10))
        s.configure("Sidebar.Muted.TLabel", background=_C_SIDEBAR, foreground=_C_SIDEBAR_M,  font=(_UI_FONT, 9))
        s.configure("Sidebar.Bold.TLabel",  background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,  font=(_UI_FONT, 13, "bold"))
        s.configure("Sidebar.Sub.TLabel",   background=_C_SIDEBAR, foreground=_C_SIDEBAR_T,  font=(_UI_FONT, 11, "bold"))
        s.configure("Status.TLabel",        background=_C_STATUS,  foreground=_C_MUTED,      font=(_UI_FONT, 9))

        # separators
        s.configure("TSeparator",         background=_C_BORDER)
        s.configure("Sidebar.TSeparator", background=_C_SIDEBAR_BD)

        # buttons — secondary (default)
        s.configure("TButton",
            font=(_UI_FONT, 10), padding=(10, 6),
            background="#dce5e8", foreground=_C_TEXT,
            bordercolor=_C_BORDER, darkcolor=_C_BORDER, lightcolor=_C_BORDER, relief="flat")
        s.map("TButton",
            background=[("active", "#c8d5da"), ("pressed", "#bccdd3"), ("disabled", "#e8eef0")],
            foreground=[("disabled", "#9badb5")],
            relief=[("active", "flat")])

        # buttons — primary accent
        s.configure("Accent.TButton",
            font=(_UI_FONT, 10, "bold"), padding=(12, 7),
            background=_C_ACCENT, foreground="white",
            bordercolor=_C_ACCENT, darkcolor=_C_ACCENT_DK, lightcolor=_C_ACCENT, relief="flat")
        s.map("Accent.TButton",
            background=[("active", _C_ACCENT_DK), ("pressed", _C_ACCENT_DK), ("disabled", "#8ec8cd")],
            foreground=[("disabled", "#d6edef")],
            relief=[("active", "flat")])

        # buttons — danger
        s.configure("Danger.TButton",
            font=(_UI_FONT, 10), padding=(10, 6),
            background=_C_CARD, foreground=_C_DANGER,
            bordercolor=_C_DANGER, darkcolor=_C_DANGER, lightcolor=_C_DANGER, relief="flat")
        s.map("Danger.TButton",
            background=[("active", "#fdf0ef"), ("pressed", "#fbe6e4")],
            foreground=[("active", _C_DANGER_DK)],
            relief=[("active", "flat")])

        # buttons — inside sidebar
        s.configure("Sidebar.TButton",
            font=(_UI_FONT, 9), padding=(8, 5),
            background=_C_SIDEBAR_H, foreground=_C_SIDEBAR_T,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD, relief="flat")
        s.map("Sidebar.TButton",
            background=[("active", "#2e4f62"), ("pressed", "#2e4f62")],
            relief=[("active", "flat")])

        s.configure("SidebarAccent.TButton",
            font=(_UI_FONT, 9, "bold"), padding=(8, 5),
            background=_C_ACCENT, foreground="white",
            bordercolor=_C_ACCENT, darkcolor=_C_ACCENT_DK, lightcolor=_C_ACCENT, relief="flat")
        s.map("SidebarAccent.TButton",
            background=[("active", _C_ACCENT_DK), ("pressed", _C_ACCENT_DK), ("disabled", "#2c6670")],
            foreground=[("disabled", "#9bc5ca")],
            relief=[("active", "flat")])

        # combobox
        s.configure("TCombobox",
            fieldbackground=_C_CARD, background=_C_CARD, foreground=_C_TEXT,
            selectbackground=_C_ACCENT, selectforeground="white", arrowcolor=_C_MUTED)
        s.map("TCombobox",
            fieldbackground=[("readonly", _C_CARD)],
            foreground=[("readonly", _C_TEXT)])

        s.configure("Sidebar.TCombobox",
            fieldbackground=_C_SIDEBAR_F, background=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T,
            selectbackground=_C_ACCENT, selectforeground="white", arrowcolor=_C_SIDEBAR_M,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)
        s.map("Sidebar.TCombobox",
            fieldbackground=[("readonly", _C_SIDEBAR_F)],
            foreground=[("readonly", _C_SIDEBAR_T)])

        # entry
        s.configure("Sidebar.TEntry",
            fieldbackground=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T,
            insertcolor=_C_SIDEBAR_T,
            bordercolor=_C_SIDEBAR_BD, darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)

        # scale
        s.configure("Sidebar.Horizontal.TScale",
            background=_C_SIDEBAR, troughcolor=_C_SIDEBAR_F,
            darkcolor=_C_SIDEBAR_BD, lightcolor=_C_SIDEBAR_BD)

        # step bar
        s.configure("Step.Active.TLabel",   background=_C_CARD, foreground=_C_ACCENT, font=(_UI_FONT, 9, "bold"))
        s.configure("Step.Done.TLabel",     background=_C_CARD, foreground=_C_TEXT,   font=(_UI_FONT, 9))
        s.configure("Step.Inactive.TLabel", background=_C_CARD, foreground=_C_MUTED,  font=(_UI_FONT, 9))

        # notebook
        s.configure("TNotebook",     background=_C_CARD, bordercolor=_C_BORDER)
        s.configure("TNotebook.Tab", background="#e8eef0", foreground=_C_MUTED,
                    padding=(12, 5), font=(_UI_FONT, 9))
        s.map("TNotebook.Tab",
            background=[("selected", _C_CARD), ("active", "#f0f5f6")],
            foreground=[("selected", _C_TEXT)])

        # treeview — main content
        s.configure("Treeview",
            font=(_UI_FONT, 9), rowheight=26,
            background=_C_CARD, fieldbackground=_C_CARD, foreground=_C_TEXT)
        s.configure("Treeview.Heading",
            font=(_UI_FONT, 9, "bold"),
            background="#e8eef0", foreground=_C_TEXT,
            bordercolor=_C_BORDER, relief="flat")
        s.map("Treeview",
            background=[("selected", "#d6ecf0")],
            foreground=[("selected", "#0a3540")])

        # treeview — inside sidebar
        s.configure("Sidebar.Treeview",
            font=(_UI_FONT, 9), rowheight=22,
            background=_C_SIDEBAR_F, fieldbackground=_C_SIDEBAR_F, foreground=_C_SIDEBAR_T)
        s.configure("Sidebar.Treeview.Heading",
            font=(_UI_FONT, 8, "bold"),
            background=_C_SIDEBAR, foreground=_C_SIDEBAR_M,
            bordercolor=_C_SIDEBAR_BD, relief="flat")
        s.map("Sidebar.Treeview",
            background=[("selected", _C_ACCENT)],
            foreground=[("selected", "white")])

    def configure_scaled_style(self, scale: float) -> None:
        self._ui_scale = scale
        s = getattr(self, "_style", ttk.Style(self))

        def font(size: int, weight: str | None = None) -> tuple:
            scaled = max(7, int(round(size * scale)))
            return (_UI_FONT, scaled, weight) if weight else (_UI_FONT, scaled)

        def pad(x: int, y: int) -> tuple[int, int]:
            return (max(3, int(round(x * scale))), max(2, int(round(y * scale))))

        s.configure("TLabel", font=font(10))
        s.configure("Card.TLabel", font=font(10))
        s.configure("Card.Muted.TLabel", font=font(9))
        s.configure("AppTitle.TLabel", font=font(17, "bold"))
        s.configure("AppSub.TLabel", font=font(10))
        s.configure("Metric.TLabel", font=font(22, "bold"))
        s.configure("Sidebar.TLabel", font=font(10))
        s.configure("Sidebar.Muted.TLabel", font=font(9))
        s.configure("Sidebar.Bold.TLabel", font=font(13, "bold"))
        s.configure("Sidebar.Sub.TLabel", font=font(11, "bold"))
        s.configure("Status.TLabel", font=font(9))

        s.configure("TButton", font=font(10), padding=pad(10, 6))
        s.configure("Accent.TButton", font=font(10, "bold"), padding=pad(12, 7))
        s.configure("Danger.TButton", font=font(10), padding=pad(10, 6))
        s.configure("Sidebar.TButton", font=font(9), padding=pad(8, 5))
        s.configure("SidebarAccent.TButton", font=font(9, "bold"), padding=pad(8, 5))
        s.configure("TNotebook.Tab", padding=pad(12, 5), font=font(9))
        s.configure("Treeview", font=font(9), rowheight=max(18, int(round(26 * scale))))
        s.configure("Treeview.Heading", font=font(9, "bold"))
        s.configure("Sidebar.Treeview", font=font(9), rowheight=max(17, int(round(22 * scale))))
        s.configure("Sidebar.Treeview.Heading", font=font(8, "bold"))
        s.configure("Step.Active.TLabel", font=font(9, "bold"))
        s.configure("Step.Done.TLabel", font=font(9))
        s.configure("Step.Inactive.TLabel", font=font(9))
