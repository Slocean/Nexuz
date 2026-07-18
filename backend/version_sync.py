"""Keep backend/version.py __version__ aligned with app_update.json history[0]."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return _ROOT


def read_channel_version(root: Path | None = None) -> str | None:
    path = (root or project_root()) / "app_update.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("history"), list) and data["history"]:
            first = data["history"][0]
            if isinstance(first, dict):
                ver = str(first.get("version") or "").strip().lstrip("v")
                if ver:
                    return ver
        if isinstance(data, dict):
            ver = str(data.get("version") or "").strip().lstrip("v")
            return ver or None
    except Exception:
        return None
    return None


def inject_version(version: str, *, root: Path | None = None) -> str:
    """Write __version__ into backend/version.py. Returns normalized version."""
    ver = str(version or "").strip().lstrip("v")
    if not ver:
        raise ValueError("empty version")

    path = (root or project_root()) / "backend" / "version.py"
    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(
        r'^__version__\s*=\s*["\'].*?["\']',
        f'__version__ = "{ver}"',
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise RuntimeError(f"failed to patch __version__ in {path}")
    if updated != text:
        path.write_text(updated, encoding="utf-8")

    # Keep already-imported module in sync (dev reloads / same process).
    try:
        import backend.version as ver_mod

        ver_mod.__version__ = ver
    except Exception:
        pass
    return ver


def sync_version_from_app_update(*, quiet: bool = False, root: Path | None = None) -> str | None:
    """
    Match backend/version.py to app_update.json latest history version.

    No-op when frozen (packaged exe) — version is already baked in.
    Returns the synced version string, or None if skipped / unavailable.
    """
    if getattr(sys, "frozen", False):
        return None

    base = root or project_root()
    ver = read_channel_version(base)
    if not ver:
        if not quiet:
            print("! version sync: no version in app_update.json")
        return None

    path = base / "backend" / "version.py"
    current = None
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'^__version__\s*=\s*["\'](.*?)["\']', text, flags=re.M)
        if m:
            current = m.group(1).strip().lstrip("v")
    except Exception:
        current = None

    if current == ver:
        if not quiet:
            print(f"OK: version already {ver}")
        return ver

    inject_version(ver, root=base)
    if not quiet:
        print(f"OK: synced version {current or '?'} → {ver} (from app_update.json)")
    return ver
