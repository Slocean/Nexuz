"""App config `browser` section: engine choice, headless, profile dir."""

from __future__ import annotations

from typing import Any

_ENGINES = ("auto", "cdp", "drission")


def get_browser_config() -> dict[str, Any]:
    from backend.paths import load_app_config

    raw = load_app_config().get("browser")
    cfg = raw if isinstance(raw, dict) else {}
    engine = str(cfg.get("engine") or "auto").strip().lower()
    if engine not in _ENGINES:
        engine = "auto"
    return {
        "engine": engine,
        "headless": bool(cfg.get("headless", True)),
        "keep_alive": bool(cfg.get("keep_alive", False)),
        "profile_dir": str(cfg.get("profile_dir") or ""),
        "edge_path": str(cfg.get("edge_path") or ""),
    }


def set_browser_config(patch: dict[str, Any]) -> dict[str, Any]:
    from backend.paths import load_app_config, save_app_config

    if not isinstance(patch, dict):
        patch = {}
    cfg = load_app_config()
    section = cfg.get("browser") if isinstance(cfg.get("browser"), dict) else {}
    if "engine" in patch and str(patch.get("engine") or "").strip().lower() in _ENGINES:
        section["engine"] = str(patch["engine"]).strip().lower()
    if "headless" in patch:
        section["headless"] = bool(patch.get("headless"))
    if "keep_alive" in patch:
        section["keep_alive"] = bool(patch.get("keep_alive"))
    if "profile_dir" in patch:
        section["profile_dir"] = str(patch.get("profile_dir") or "").strip()
    if "edge_path" in patch:
        section["edge_path"] = str(patch.get("edge_path") or "").strip()
    cfg["browser"] = section
    save_app_config(cfg)
    return get_browser_config()
