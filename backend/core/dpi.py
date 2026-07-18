"""DPI scaling helpers for Windows logical ↔ physical pixels (per-monitor aware)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
from typing import Any


def get_dpi_scale() -> float:
    """Return primary / system DPI scale (e.g. 1.25 for 125%). Fallback for legacy callers."""
    if sys.platform != "win32":
        return 1.0
    try:
        user32 = ctypes.windll.user32
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


def get_dpi_for_point(x: int, y: int) -> int:
    """DPI (96-based) of the monitor containing screen point (x, y)."""
    if sys.platform != "win32":
        return 96
    try:
        user32 = ctypes.windll.user32
        point = ctypes.wintypes.POINT(int(x), int(y))
        # MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromPoint(point, 2)
        if not hmon:
            return int(round(get_dpi_scale() * 96))
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        # MDT_EFFECTIVE_DPI = 0
        hr = ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if hr == 0 and dpi_x.value:
            return int(dpi_x.value)
    except Exception:
        pass
    try:
        return int(ctypes.windll.user32.GetDpiForSystem() or 96)
    except Exception:
        return 96


def get_dpi_scale_for_point(x: int, y: int) -> float:
    return max(0.5, get_dpi_for_point(x, y) / 96.0)


def get_dpi_for_hwnd(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return 96
    try:
        dpi = int(ctypes.windll.user32.GetDpiForWindow(int(hwnd)) or 0)
        if dpi > 0:
            return dpi
    except Exception:
        pass
    return 96


def monitor_info_at_point(x: int, y: int) -> dict[str, Any]:
    """Compact monitor descriptor for coord_space / debugging."""
    dpi = get_dpi_for_point(x, y)
    info: dict[str, Any] = {"dpi": dpi, "dpi_scale": dpi / 96.0, "x": int(x), "y": int(y)}
    if sys.platform != "win32":
        return info
    try:
        user32 = ctypes.windll.user32
        point = ctypes.wintypes.POINT(int(x), int(y))
        hmon = user32.MonitorFromPoint(point, 2)
        if not hmon:
            return info

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            info["monitor"] = {
                "left": int(mi.rcMonitor.left),
                "top": int(mi.rcMonitor.top),
                "right": int(mi.rcMonitor.right),
                "bottom": int(mi.rcMonitor.bottom),
            }
    except Exception:
        pass
    return info


def logical_to_physical(x: float, y: float, scale: float | None = None) -> tuple[int, int]:
    s = scale if scale is not None else get_dpi_scale()
    return int(round(x * s)), int(round(y * s))


def physical_to_logical(x: float, y: float, scale: float | None = None) -> tuple[int, int]:
    s = scale if scale is not None else get_dpi_scale()
    if s == 0:
        return int(x), int(y)
    return int(round(x / s)), int(round(y / s))


def screen_size_logical() -> tuple[int, int]:
    """Primary screen size in logical/physical pixels (pyautogui / SM_CXSCREEN)."""
    import pyautogui

    w, h = pyautogui.size()
    return int(w), int(h)


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """
    Virtual desktop bounds as (left, top, right, bottom) exclusive bottom-right.
    Covers all monitors; required for multi-monitor coordinate validation.
    """
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
            top = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
            width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
            height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
            if width > 0 and height > 0:
                return left, top, left + width, top + height
        except Exception:
            pass
    w, h = screen_size_logical()
    return 0, 0, w, h


def virtual_screen_size() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the virtual desktop."""
    left, top, right, bottom = virtual_screen_rect()
    return left, top, max(1, right - left), max(1, bottom - top)
