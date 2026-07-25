"""Multi-monitor-safe mouse playback via Win32 APIs.

PyAutoGUI's moveTo/click only understand the primary monitor size on many
Windows setups — secondary-monitor virtual coords (e.g. x>=2560 or y!=0 origin)
get remapped and land in the wrong place. SetCursorPos / SendInput use the same
virtual-desktop space as mss and ClientToScreen.
"""

from __future__ import annotations

import sys
import time
from typing import Literal

ButtonName = Literal["left", "right", "middle"]


def _supported() -> bool:
    return sys.platform == "win32"


def get_cursor_pos() -> tuple[int, int]:
    if not _supported():
        import pyautogui

        p = pyautogui.position()
        return int(p.x), int(p.y)
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError("GetCursorPos failed")
    return int(pt.x), int(pt.y)


def move_to(x: int, y: int, *, duration: float = 0.0) -> tuple[int, int]:
    """Move cursor to virtual-desktop (x, y). Returns the position after move."""
    xi, yi = int(x), int(y)
    if not _supported():
        import pyautogui

        pyautogui.moveTo(xi, yi, duration=max(0.0, float(duration)))
        return get_cursor_pos()

    import ctypes

    user32 = ctypes.windll.user32
    duration = max(0.0, float(duration))
    if duration <= 0.001:
        if not user32.SetCursorPos(xi, yi):
            raise OSError(f"SetCursorPos({xi}, {yi}) failed")
        return get_cursor_pos()

    x0, y0 = get_cursor_pos()
    steps = max(2, int(duration * 60))
    for i in range(1, steps + 1):
        t = i / steps
        # ease-out-ish without importing math-heavy helpers
        t = 1.0 - (1.0 - t) * (1.0 - t)
        cx = int(round(x0 + (xi - x0) * t))
        cy = int(round(y0 + (yi - y0) * t))
        user32.SetCursorPos(cx, cy)
        time.sleep(duration / steps)
    user32.SetCursorPos(xi, yi)
    return get_cursor_pos()


def _button_flags(button: ButtonName) -> tuple[int, int]:
    # winuser.h MOUSEEVENTF_*
    if button == "right":
        return 0x0008, 0x0010  # RIGHTDOWN, RIGHTUP
    if button == "middle":
        return 0x0020, 0x0040  # MIDDLEDOWN, MIDDLEUP
    return 0x0002, 0x0004  # LEFTDOWN, LEFTUP


def _send_button(button: ButtonName, *, down: bool) -> None:
    if not _supported():
        import pyautogui

        if down:
            pyautogui.mouseDown(button=button)
        else:
            pyautogui.mouseUp(button=button)
        return

    import ctypes

    down_f, up_f = _button_flags(button)
    flag = down_f if down else up_f
    # mouse_event is adequate for button clicks at the current cursor position.
    ctypes.windll.user32.mouse_event(flag, 0, 0, 0, 0)


def click_at(
    x: int,
    y: int,
    *,
    button: ButtonName = "left",
    clicks: int = 1,
    move_duration: float = 0.0,
    settle_s: float = 0.05,
    click_interval_s: float = 0.05,
) -> dict[str, int | str]:
    """Move to (x, y) then click. Returns intended + actual cursor position."""
    btn: ButtonName = button if button in ("left", "right", "middle") else "left"
    n = max(1, int(clicks))
    move_to(x, y, duration=move_duration)
    if settle_s > 0:
        time.sleep(settle_s)
    for i in range(n):
        _send_button(btn, down=True)
        time.sleep(0.01)
        _send_button(btn, down=False)
        if i + 1 < n and click_interval_s > 0:
            time.sleep(click_interval_s)
    ax, ay = get_cursor_pos()
    return {
        "x": int(x),
        "y": int(y),
        "actual_x": ax,
        "actual_y": ay,
        "button": btn,
    }


def drag_to(
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    *,
    duration: float = 0.3,
    button: ButtonName = "left",
) -> None:
    btn: ButtonName = button if button in ("left", "right", "middle") else "left"
    move_to(from_x, from_y, duration=0)
    time.sleep(0.02)
    _send_button(btn, down=True)
    time.sleep(0.02)
    move_to(to_x, to_y, duration=max(0.0, float(duration)))
    time.sleep(0.02)
    _send_button(btn, down=False)
