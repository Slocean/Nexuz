"""DPI scaling helpers for Windows logical ↔ physical pixels."""

from __future__ import annotations

import ctypes
import sys


def get_dpi_scale() -> float:
    """Return primary monitor DPI scale (e.g. 1.25 for 125%)."""
    if sys.platform != "win32":
        return 1.0
    try:
        user32 = ctypes.windll.user32
        # Prefer per-monitor awareness if available
        try:
            awareness = ctypes.c_int()
            ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
        except Exception:
            pass
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except Exception:
            hdc = user32.GetDC(0)
            try:
                LOGPIXELSX = 88
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                return dpi / 96.0 if dpi else 1.0
            finally:
                user32.ReleaseDC(0, hdc)
    except Exception:
        return 1.0


def logical_to_physical(x: float, y: float, scale: float | None = None) -> tuple[int, int]:
    s = scale if scale is not None else get_dpi_scale()
    return int(round(x * s)), int(round(y * s))


def physical_to_logical(x: float, y: float, scale: float | None = None) -> tuple[int, int]:
    s = scale if scale is not None else get_dpi_scale()
    if s == 0:
        return int(x), int(y)
    return int(round(x / s)), int(round(y / s))


def screen_size_logical() -> tuple[int, int]:
    """Screen size in logical pixels (what UI / pyautogui typically use)."""
    import pyautogui

    w, h = pyautogui.size()
    return int(w), int(h)
