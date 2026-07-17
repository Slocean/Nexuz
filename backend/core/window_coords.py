"""Windows target-window coordinate capture and playback helpers."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import time
from typing import Any


def _supported() -> bool:
    return sys.platform == "win32"


def _window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _window_pid(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _process_name(pid: int) -> str:
    try:
        import psutil

        return str(psutil.Process(pid).name() or "")
    except Exception:
        return ""


def _client_geometry(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = ctypes.wintypes.POINT(0, 0)
    if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    return int(origin.x), int(origin.y), width, height


def capture_window_target(x: int, y: int) -> dict[str, Any] | None:
    """Describe the top-level window under a physical screen point."""
    if not _supported():
        return None
    try:
        user32 = ctypes.windll.user32
        point = ctypes.wintypes.POINT(int(x), int(y))
        hwnd = int(user32.WindowFromPoint(point) or 0)
        if not hwnd:
            return None
        hwnd = int(user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT
        geometry = _client_geometry(hwnd)
        if geometry is None:
            return None
        left, top, width, height = geometry
        pid = _window_pid(hwnd)
        # Never bind automation to this Nexuz process itself.
        if pid == os.getpid():
            return None
        try:
            dpi = int(user32.GetDpiForWindow(hwnd) or 96)
        except Exception:
            dpi = 96
        return {
            "pid": pid,
            "process_name": _process_name(pid),
            "class_name": _window_class(hwnd),
            "title": _window_text(hwnd),
            "client_width": width,
            "client_height": height,
            "dpi": dpi,
            "point_norm": [
                (int(x) - left) / width,
                (int(y) - top) / height,
            ],
        }
    except Exception:
        return None


def _find_window(target: dict[str, Any]) -> int:
    user32 = ctypes.windll.user32
    stored_pid = int(target.get("pid") or 0)
    if stored_pid:
        # PID is only a fast path; saved flows may run after the process restarts.
        candidates: list[tuple[int, int]] = []
        expected_class = str(target.get("class_name") or "")
        expected_title = str(target.get("title") or "")

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def same_pid(hwnd, _lparam):
            if _window_pid(int(hwnd)) == stored_pid and user32.IsWindowVisible(hwnd):
                hwnd_i = int(hwnd)
                score = 0
                if expected_class and _window_class(hwnd_i) == expected_class:
                    score += 2
                if expected_title and _window_text(hwnd_i) == expected_title:
                    score += 3
                candidates.append((score, hwnd_i))
            return True

        user32.EnumWindows(same_pid, 0)
        if candidates:
            return max(candidates)[1]

    expected_process = str(target.get("process_name") or "").lower()
    expected_class = str(target.get("class_name") or "")
    expected_title = str(target.get("title") or "")
    ranked: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def collect(hwnd, _lparam):
        hwnd_i = int(hwnd)
        if not user32.IsWindowVisible(hwnd) or not _client_geometry(hwnd_i):
            return True
        process = _process_name(_window_pid(hwnd_i)).lower()
        if expected_process and process != expected_process:
            return True
        score = 4 if expected_process and process == expected_process else 0
        cls = _window_class(hwnd_i)
        title = _window_text(hwnd_i)
        if expected_class and cls == expected_class:
            score += 2
        if expected_title and title == expected_title:
            score += 3
        elif expected_title and (expected_title in title or title in expected_title):
            score += 1
        ranked.append((score, hwnd_i))
        return True

    user32.EnumWindows(collect, 0)
    return max(ranked, default=(0, 0))[1]


def resolve_window_point(target: dict[str, Any]) -> tuple[int, int, int]:
    if not _supported() or not isinstance(target, dict):
        raise RuntimeError("窗口相对坐标仅支持 Windows")
    hwnd = _find_window(target)
    if not hwnd:
        raise RuntimeError(
            f"未找到目标窗口：{target.get('process_name') or target.get('title') or '未知窗口'}"
        )
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.08)
    geometry = _client_geometry(hwnd)
    if geometry is None:
        raise RuntimeError("无法读取目标窗口客户区")
    left, top, width, height = geometry
    norm = target.get("point_norm")
    if not isinstance(norm, (list, tuple)) or len(norm) != 2:
        raise RuntimeError("窗口坐标缺少 point_norm")
    x = int(round(left + float(norm[0]) * width))
    y = int(round(top + float(norm[1]) * height))
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return x, y, hwnd
