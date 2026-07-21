"""Resolve project root and user data directories for source / frozen runs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    """Writable directory next to the executable (or project root in dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


def default_data_dir() -> Path:
    """Default user data root: %LOCALAPPDATA%\\Nexuz"""
    return _local_app_data() / "Nexuz"


def config_path() -> Path:
    """App config always lives under the default AppData root (findable after relocate)."""
    return default_data_dir() / "config.json"


def load_app_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_app_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_data_dir(*, create: bool = False) -> Path:
    """
    Resolved user data root (flows / templates / …).
    Does not create the directory unless create=True (e.g. on save).
    """
    cfg = load_app_config()
    custom = cfg.get("data_dir")
    if custom and str(custom).strip():
        root = Path(str(custom).strip())
    else:
        root = default_data_dir()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def set_data_dir(path: str | Path | None) -> Path:
    """
    Persist custom data_dir. Pass None / empty to reset to default AppData.
    Does not create the target folder.
    """
    cfg = load_app_config()
    if path is None or not str(path).strip():
        cfg.pop("data_dir", None)
        save_app_config(cfg)
        return default_data_dir()
    resolved = Path(str(path).strip()).expanduser()
    cfg["data_dir"] = str(resolved)
    save_app_config(cfg)
    return resolved


def get_notice_read_id() -> str:
    """Sticky notice dismiss id (survives onefile file:// origin changes)."""
    return str(load_app_config().get("notice_read_id") or "")


def set_notice_read_id(notice_id: str | None) -> str:
    cfg = load_app_config()
    value = str(notice_id or "").strip()
    if value:
        cfg["notice_read_id"] = value
    else:
        cfg.pop("notice_read_id", None)
    save_app_config(cfg)
    return value


def ai_dir(*, create: bool = False) -> Path:
    """AI data root: conversations, future drafts — under resolved data_dir."""
    root = get_data_dir(create=create) / "ai"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root
