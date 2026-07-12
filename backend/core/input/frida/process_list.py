"""Enrich process list with window titles / exe paths so same-name PIDs are distinguishable."""

from __future__ import annotations

import os
import sys
from typing import Any


def _windows_visible_titles_by_pid() -> dict[int, list[str]]:
    """Map pid -> visible top-level window titles (Windows)."""
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles: dict[int, list[str]] = {}

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    IsWindowVisible = user32.IsWindowVisible
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextW = user32.GetWindowTextW
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindow = user32.GetWindow
    GW_OWNER = 4

    def callback(hwnd, _lparam):
        try:
            if not IsWindowVisible(hwnd):
                return True
            # Skip owned windows (tooltips, etc.) — keep top-level app windows
            if GetWindow(hwnd, GW_OWNER):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = (buf.value or "").strip()
            if not title:
                return True
            pid = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            p = int(pid.value)
            if p <= 0:
                return True
            titles.setdefault(p, [])
            if title not in titles[p]:
                titles[p].append(title)
        except Exception:
            pass
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return titles


def _exe_by_pid(pids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    if not pids:
        return out
    try:
        import psutil
    except ImportError:
        return out
    for pid in pids:
        try:
            out[pid] = str(psutil.Process(pid).exe() or "")
        except (psutil.Error, OSError, Exception):
            continue
    return out


def enrich_process_rows(
    rows: list[dict[str, Any]],
    *,
    query: str | None = None,
    only_with_window: bool = True,
) -> list[dict[str, Any]]:
    """
    Add window_title / exe / display fields.
    When only_with_window=True (default), drop processes with no visible window —
    this removes most duplicate helper/worker processes for games.
    """
    titles_map = _windows_visible_titles_by_pid()
    q = (query or "").strip().lower()

    # First pass: decide candidates (avoid exe() on hundreds of helper PIDs)
    candidates: list[tuple[dict[str, Any], list[str], str]] = []
    for row in rows:
        pid = int(row.get("pid") or 0)
        name = str(row.get("name") or "")
        if not pid or not name:
            continue
        win_titles = titles_map.get(pid) or []
        window_title = win_titles[0] if win_titles else ""
        if only_with_window and not window_title:
            continue
        # Cheap prefilter before exe lookup
        if q:
            hay0 = f"{name} {pid} {window_title} {' '.join(win_titles)}".lower()
            if q not in hay0:
                # may still match exe path — keep if no query on title/name only when not only_with_window
                # For speed: if query looks like path fragment, keep candidates with window
                if only_with_window or not any(ch in q for ch in ("\\", "/", ".")):
                    continue
        candidates.append(({"pid": pid, "name": name}, win_titles, window_title))

    exe_map = _exe_by_pid({int(c[0]["pid"]) for c in candidates})

    enriched: list[dict[str, Any]] = []
    for base, win_titles, window_title in candidates:
        pid = int(base["pid"])
        name = str(base["name"])
        exe = exe_map.get(pid) or ""
        exe_base = os.path.basename(exe) if exe else ""

        if q:
            hay = " ".join([name, str(pid), window_title, exe, exe_base, " ".join(win_titles)]).lower()
            if q not in hay:
                continue

        if window_title:
            display = f"{window_title}  ·  {name}  ·  PID {pid}"
        elif exe_base and exe_base.lower() != name.lower():
            display = f"{name}  ·  {exe_base}  ·  PID {pid}"
        else:
            display = f"{name}  ·  PID {pid}"

        enriched.append(
            {
                "pid": pid,
                "name": name,
                "window_title": window_title,
                "window_titles": win_titles,
                "exe": exe,
                "exe_base": exe_base,
                "has_window": bool(window_title),
                "display": display,
            }
        )

    enriched.sort(
        key=lambda r: (
            0 if r.get("has_window") else 1,
            str(r.get("window_title") or "").lower(),
            str(r.get("name") or "").lower(),
            int(r["pid"]),
        )
    )
    return enriched
