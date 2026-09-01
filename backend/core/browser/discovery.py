"""Locate a Chromium browser on Windows and parse DevToolsActivePort."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_EDGE_RELATIVE = [
    r"Microsoft\Edge\Application\msedge.exe",
]
_CHROME_RELATIVE = [
    r"Google\Chrome\Application\chrome.exe",
]
_PROGRAM_DIRS = [
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.environ.get("LocalAppData", ""),
]


def _exists(p: str | Path | None) -> str:
    if not p:
        return ""
    try:
        path = Path(p)
        if path.is_file():
            return str(path)
    except OSError:
        pass
    return ""


def _reg_app_path(exe_name: str) -> str:
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for hive in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",):
                try:
                    with winreg.OpenKey(root, rf"{hive}\{exe_name}") as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        found = _exists(val)
                        if found:
                            return found
                except OSError:
                    continue
    except Exception:
        pass
    return ""


def _scan_program_dirs(relative: list[str]) -> str:
    for base in _PROGRAM_DIRS:
        if not base:
            continue
        for rel in relative:
            found = _exists(Path(base) / rel)
            if found:
                return found
    return ""


def find_edge(configured_path: str = "") -> str:
    found = _exists(configured_path)
    if found:
        return found
    found = _reg_app_path("msedge.exe")
    if found:
        return found
    return _scan_program_dirs(_EDGE_RELATIVE)


def find_chrome(configured_path: str = "") -> str:
    found = _exists(configured_path)
    if found:
        return found
    found = _reg_app_path("chrome.exe")
    if found:
        return found
    return _scan_program_dirs(_CHROME_RELATIVE)


def find_browser(configured_path: str = "") -> str:
    """Prefer Edge (always present on Win10/11), then Chrome, then PATH."""
    found = find_edge(configured_path)
    if found:
        return found
    found = find_chrome()
    if found:
        return found
    for name in ("msedge", "chrome"):
        which = shutil.which(name)
        if which:
            return which
    return ""


def parse_devtools_port_file(user_data_dir: str | Path) -> tuple[int, str]:
    """Parse DevToolsActivePort → (port, browser_ws_path). Raises FileNotFoundError."""
    path = Path(user_data_dir) / "DevToolsActivePort"
    text = path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"empty DevToolsActivePort: {path}")
    return int(lines[0]), lines[1] if len(lines) > 1 else ""
