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
    """Resolve client-normalized point to current screen coords (DPI-safe via point_norm)."""
    if not _supported() or not isinstance(target, dict):
        raise RuntimeError("窗口相对坐标仅支持 Windows")
    hwnd = _find_window(target)
    if not hwnd:
        raise RuntimeError(
            f"未找到目标窗口：{target.get('process_name') or target.get('title') or '未知窗口'}"
        )
    activate_hwnd(hwnd)
    geometry = _client_geometry(hwnd)
    if geometry is None:
        raise RuntimeError("无法读取目标窗口客户区")
    left, top, width, height = geometry
    norm = target.get("point_norm")
    if not isinstance(norm, (list, tuple)) or len(norm) != 2:
        raise RuntimeError("窗口坐标缺少 point_norm")
    # point_norm is relative to live client size (after restore), so window move /
    # per-monitor DPI changes stay correct without extra scale math.
    x = int(round(left + float(norm[0]) * width))
    y = int(round(top + float(norm[1]) * height))
    return x, y, hwnd


def criteria_from_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Build a match dict from block params (title / process_name / class_name)."""
    p = params if isinstance(params, dict) else {}
    out: dict[str, Any] = {}
    title = str(p.get("title") or "").strip()
    process = str(p.get("process_name") or "").strip()
    cls = str(p.get("class_name") or "").strip()
    if title:
        out["title"] = title
    if process:
        out["process_name"] = process
    if cls:
        out["class_name"] = cls
    return out


def criteria_has_match_fields(criteria: dict[str, Any]) -> bool:
    return bool(
        str(criteria.get("title") or "").strip()
        or str(criteria.get("process_name") or "").strip()
        or str(criteria.get("class_name") or "").strip()
    )


def find_matching_window(criteria: dict[str, Any], *, min_score: int = 1) -> int:
    """Find a visible top-level window; require min_score so empty criteria never match."""
    if not _supported() or not isinstance(criteria, dict):
        return 0
    if not criteria_has_match_fields(criteria):
        return 0
    hwnd = _find_window(criteria)
    if not hwnd:
        return 0
    # Re-score to reject accidental zero-score picks from _find_window.
    expected_process = str(criteria.get("process_name") or "").lower()
    expected_class = str(criteria.get("class_name") or "")
    expected_title = str(criteria.get("title") or "")
    score = 0
    process = _process_name(_window_pid(hwnd)).lower()
    if expected_process and process == expected_process:
        score += 4
    elif expected_process:
        return 0
    cls = _window_class(hwnd)
    title = _window_text(hwnd)
    if expected_class and cls == expected_class:
        score += 2
    elif expected_class:
        return 0
    if expected_title and title == expected_title:
        score += 3
    elif expected_title and (expected_title in title or title in expected_title):
        score += 1
    elif expected_title:
        return 0
    return hwnd if score >= min_score else 0


def describe_hwnd(hwnd: int) -> dict[str, Any]:
    if not hwnd:
        return {}
    pid = _window_pid(hwnd)
    geometry = _client_geometry(hwnd)
    info: dict[str, Any] = {
        "hwnd": int(hwnd),
        "pid": pid,
        "process_name": _process_name(pid),
        "class_name": _window_class(hwnd),
        "title": _window_text(hwnd),
    }
    if geometry:
        _left, _top, width, height = geometry
        info["client_width"] = width
        info["client_height"] = height
    return info


def list_top_level_windows(*, exclude_pid: int | None = None) -> list[dict[str, Any]]:
    """Visible top-level windows for picker UI (newest/largest titles first)."""
    if not _supported():
        return []
    skip = int(exclude_pid if exclude_pid is not None else os.getpid())
    user32 = ctypes.windll.user32
    items: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def collect(hwnd, _lparam):
        hwnd_i = int(hwnd)
        if not user32.IsWindowVisible(hwnd):
            return True
        # Only top-level (no owner)
        if user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        title = _window_text(hwnd_i).strip()
        if not title:
            return True
        pid = _window_pid(hwnd_i)
        if pid == skip:
            return True
        if not _client_geometry(hwnd_i):
            return True
        info = describe_hwnd(hwnd_i)
        info["label"] = f"{title}  ·  {info.get('process_name') or '?'}"
        items.append(info)
        return True

    user32.EnumWindows(collect, 0)
    items.sort(key=lambda w: (str(w.get("title") or "").lower(), str(w.get("process_name") or "").lower()))
    return items


def capture_window_under_point(x: int, y: int) -> dict[str, Any] | None:
    """Top-level window at screen point — for「点选窗口」."""
    if not _supported():
        return None
    try:
        user32 = ctypes.windll.user32
        point = ctypes.wintypes.POINT(int(x), int(y))
        hwnd = int(user32.WindowFromPoint(point) or 0)
        if not hwnd:
            return None
        hwnd = int(user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT
        pid = _window_pid(hwnd)
        if pid == os.getpid():
            return None
        if not user32.IsWindowVisible(hwnd):
            return None
        info = describe_hwnd(hwnd)
        if not str(info.get("title") or "").strip() and not str(info.get("process_name") or "").strip():
            return None
        info["label"] = (
            f"{info.get('title') or '(无标题)'}  ·  {info.get('process_name') or '?'}"
        )
        return info
    except Exception:
        return None


def activate_hwnd(hwnd: int) -> None:
    if not hwnd or not _supported():
        return
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.08)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def close_hwnd(hwnd: int, *, force: bool = False) -> None:
    if not hwnd or not _supported():
        raise RuntimeError("无效窗口句柄")
    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    if not force:
        return
    time.sleep(0.35)
    if not user32.IsWindow(hwnd):
        return
    pid = _window_pid(hwnd)
    if not pid or pid == os.getpid():
        return
    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if handle:
        try:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
