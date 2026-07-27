"""App UI / preference settings persisted in config.json `ui` section."""

from __future__ import annotations

from typing import Any

from backend.core.hotkey_prefs import DEFAULTS as HOTKEY_DEFAULTS
from backend.core.hotkey_prefs import SLOTS as HOTKEY_SLOTS
from backend.core.hotkey_prefs import normalize_hotkey
from backend.paths import load_app_config, save_app_config

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "hideWindowOnRecord": False,
    "showToolbarLabels": True,
    "nodeContextMenuMode": "grouped",
    "hideSidePanelsOnSettings": True,
    "autoSaveEnabled": False,
    "autoSaveIntervalSec": 60,
    "saveAfterRun": True,
    "defaultCaptureMode": "coord",
    "defaultPickMethod": "screenshot",
    "defaultCoordinateMode": "window_client",
    "defaultOutputCoordinateMode": "window_client",
    "defaultNodeIntervalMs": 500,
    "themeName": "Ocean",
    "themeMode": "dark",
    "diagLogging": False,
    "autoCheckUpdate": True,
    "aiMode": "chat",
    "hotkeys": {slot: list(keys) for slot, keys in HOTKEY_DEFAULTS.items()},
}

_BOOL_KEYS = {
    "hideWindowOnRecord",
    "showToolbarLabels",
    "hideSidePanelsOnSettings",
    "autoSaveEnabled",
    "saveAfterRun",
    "diagLogging",
    "autoCheckUpdate",
}

_INT_KEYS = {
    "autoSaveIntervalSec",
    "defaultNodeIntervalMs",
}


def _default_hotkeys() -> dict[str, list[str]]:
    return {slot: list(HOTKEY_DEFAULTS[slot]) for slot in HOTKEY_SLOTS}


def _normalize_hotkeys(raw: Any) -> dict[str, list[str]]:
    out = _default_hotkeys()
    if not isinstance(raw, dict):
        return out
    for slot in HOTKEY_SLOTS:
        if slot in raw:
            out[slot] = list(normalize_hotkey(raw.get(slot), default=HOTKEY_DEFAULTS[slot]))
    return out


def normalize_ui_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_UI_SETTINGS)
    out["hotkeys"] = _default_hotkeys()

    for key, default in DEFAULT_UI_SETTINGS.items():
        if key == "hotkeys":
            continue
        if key not in data:
            continue
        val = data[key]
        if key in _BOOL_KEYS:
            out[key] = bool(val)
        elif key == "autoSaveIntervalSec":
            try:
                n = int(val)
            except (TypeError, ValueError):
                n = int(default)
            out[key] = min(3600, max(10, n))
        elif key == "defaultNodeIntervalMs":
            try:
                n = int(val)
            except (TypeError, ValueError):
                n = int(default)
            out[key] = max(0, n)
        elif key == "nodeContextMenuMode":
            out[key] = "flat" if val == "flat" else "grouped"
        elif key == "defaultCaptureMode":
            out[key] = "frida_ui" if val == "frida_ui" else "coord"
        elif key == "defaultPickMethod":
            out[key] = "live" if val == "live" else "screenshot"
        elif key == "defaultCoordinateMode":
            if val in ("window_client", "virtual_norm", "screen_abs"):
                out[key] = val
        elif key == "defaultOutputCoordinateMode":
            if val in ("region_rel", "screen_abs", "window_client"):
                out[key] = val
        elif key == "themeMode":
            out[key] = "light" if val == "light" else "dark"
        elif key == "themeName":
            out[key] = str(val or default).strip() or str(default)
        elif key == "aiMode":
            out[key] = "flow" if str(val or "").strip().lower() in {"flow", "orch", "orchestration"} else "chat"
        else:
            out[key] = val if val is not None else default

    if "hotkeys" in data:
        out["hotkeys"] = _normalize_hotkeys(data.get("hotkeys"))
    return out


def get_ui_settings() -> dict[str, Any]:
    cfg = load_app_config()
    raw = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    return normalize_ui_settings(raw)


def ui_settings_persisted() -> bool:
    cfg = load_app_config()
    return isinstance(cfg.get("ui"), dict) and bool(cfg.get("ui"))


def patch_ui_settings(patch: dict[str, Any] | None) -> dict[str, Any]:
    """Merge patch into stored ui settings and return the full normalized result."""
    patch = patch if isinstance(patch, dict) else {}
    cfg = load_app_config()
    current_raw = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    merged = dict(current_raw)
    for key, value in patch.items():
        if key in DEFAULT_UI_SETTINGS or key == "hotkeys":
            merged[key] = value
    normalized = normalize_ui_settings(merged)
    cfg["ui"] = normalized
    save_app_config(cfg)
    return normalized
