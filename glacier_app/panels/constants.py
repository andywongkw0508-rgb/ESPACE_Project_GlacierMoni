from __future__ import annotations

import platform

_SYS = platform.system()
_UI_FONT   = "Helvetica Neue" if _SYS == "Darwin" else ("Segoe UI"   if _SYS == "Windows" else "DejaVu Sans")
_MONO_FONT = "Menlo"          if _SYS == "Darwin" else ("Consolas"   if _SYS == "Windows" else "DejaVu Sans Mono")

_C_SIDEBAR    = "#1e2d35"
_C_SIDEBAR_H  = "#26404f"
_C_SIDEBAR_T  = "#cce0e8"
_C_SIDEBAR_M  = "#728f9a"
_C_SIDEBAR_BD = "#2c4252"
_C_SIDEBAR_F  = "#253c49"
_C_ACCENT     = "#1e9ea8"
_C_ACCENT_DK  = "#178590"
_C_APP_BG     = "#edf1f2"
_C_CARD       = "#ffffff"
_C_TEXT       = "#1f2d33"
_C_MUTED      = "#617078"
_C_BORDER     = "#d4dde1"
_C_DANGER     = "#c0392b"
_C_DANGER_DK  = "#a93226"
_C_TREE_ALT   = "#f4f8f9"
_C_STATUS     = "#e3eaec"
