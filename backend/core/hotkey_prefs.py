"""User-configurable global hotkeys."""

from __future__ import annotations

from typing import Any, Iterable

# Defaults match historical behavior.
DEFAULTS: dict[str, tuple[str, ...]] = {
    "start_run": ("x", "f3"),
    "stop_run": ("x", "f4"),
    "pause_run": ("x", "f5"),
    "record_stop": ("x", "f10"),
}

# Back-compat aliases
DEFAULT_RECORD_STOP = DEFAULTS["record_stop"]
START_RUN_HOTKEY = DEFAULTS["start_run"]
STOP_RUN_HOTKEY = DEFAULTS["stop_run"]
PAUSE_RUN_HOTKEY = DEFAULTS["pause_run"]

SLOTS = tuple(DEFAULTS.keys())

_MODS = ("ctrl", "alt", "shift", "win")
_MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

_prefs: dict[str, tuple[str, ...]] = {k: v for k, v in DEFAULTS.items()}


def _norm_key(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if not s:
        return None
    if s in ("control", "ctl"):
        return "ctrl"
    if s in ("option", "opt"):
        return "alt"
    if s in ("meta", "cmd", "super"):
        return "win"
    if s in ("escape",):
        return "esc"
    if s.startswith("f") and s[1:].isdigit():
        n = int(s[1:])
        if 1 <= n <= 24:
            return f"f{n}"
        return None
    if len(s) == 1 and (s.isalnum() or s in (" ",)):
        return "space" if s == " " else s
    if s in _MODS or s in (
        "enter",
        "space",
        "tab",
        "esc",
        "backspace",
        "delete",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "pageup",
        "pagedown",
        "insert",
    ):
        return s
    return s if s.isalnum() else None


def normalize_hotkey(
    keys: Iterable[Any] | None,
    *,
    default: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    fallback = default if default is not None else DEFAULT_RECORD_STOP
    items: list[str] = []
    seen: set[str] = set()
    for raw in keys or []:
        k = _norm_key(raw)
        if not k or k in seen:
            continue
        seen.add(k)
        items.append(k)
    if not items:
        return fallback
    mods = [m for m in _MODS if m in items]
    others = [k for k in items if k not in _MODS]
    if not others:
        return fallback
    trigger = others[-1]
    held = others[:-1]
    return tuple(mods + held + [trigger])


def format_hotkey_label(keys: Iterable[Any] | None, *, default: tuple[str, ...] | None = None) -> str:
    norm = normalize_hotkey(keys, default=default)
    parts: list[str] = []
    for k in norm:
        if k in _MOD_LABEL:
            parts.append(_MOD_LABEL[k])
        elif k.startswith("f") and k[1:].isdigit():
            parts.append(k.upper())
        elif len(k) == 1:
            parts.append(k.upper())
        else:
            parts.append(k)
    return "+".join(parts)


def to_pynput_hotkey(keys: Iterable[Any] | None, *, default: tuple[str, ...] | None = None) -> str:
    """pynput.GlobalHotKeys format, e.g. x+<f10> or <ctrl>+<f9>."""
    norm = normalize_hotkey(keys, default=default)
    parts: list[str] = []
    for k in norm:
        if k in _MODS or (k.startswith("f") and k[1:].isdigit()):
            parts.append(f"<{k}>")
        else:
            parts.append(k)
    return "+".join(parts)


def get_hotkey(slot: str) -> tuple[str, ...]:
    key = str(slot or "").strip()
    if key not in DEFAULTS:
        return DEFAULT_RECORD_STOP
    return _prefs.get(key) or DEFAULTS[key]


def get_hotkey_label(slot: str) -> str:
    return format_hotkey_label(get_hotkey(slot), default=DEFAULTS.get(slot, DEFAULT_RECORD_STOP))


def get_all_hotkeys() -> dict[str, list[str]]:
    return {slot: list(get_hotkey(slot)) for slot in SLOTS}


def get_all_hotkey_labels() -> dict[str, str]:
    return {slot: get_hotkey_label(slot) for slot in SLOTS}


def get_defaults() -> dict[str, list[str]]:
    return {slot: list(keys) for slot, keys in DEFAULTS.items()}


def set_hotkey(slot: str, keys: Iterable[Any] | None) -> tuple[str, ...]:
    key = str(slot or "").strip()
    if key not in DEFAULTS:
        raise ValueError(f"未知快捷键: {slot}")
    _prefs[key] = normalize_hotkey(keys, default=DEFAULTS[key])
    return _prefs[key]


def apply_hotkeys(prefs: dict[str, Any] | None) -> dict[str, Any]:
    """
    Merge prefs for known slots. Rejects duplicate combos.
    Returns {ok, hotkeys, labels, error?}.
    """
    prefs = prefs if isinstance(prefs, dict) else {}
    draft = {slot: get_hotkey(slot) for slot in SLOTS}
    for slot in SLOTS:
        if slot in prefs:
            draft[slot] = normalize_hotkey(prefs.get(slot), default=DEFAULTS[slot])

    seen: dict[tuple[str, ...], str] = {}
    for slot, keys in draft.items():
        if keys in seen:
            a, b = seen[keys], slot
            label = format_hotkey_label(keys)
            return {
                "ok": False,
                "error": f"快捷键冲突：{label} 同时用于「{a}」与「{b}」",
                "hotkeys": get_all_hotkeys(),
                "labels": get_all_hotkey_labels(),
            }
        seen[keys] = slot

    for slot, keys in draft.items():
        _prefs[slot] = keys
    return {
        "ok": True,
        "hotkeys": get_all_hotkeys(),
        "labels": get_all_hotkey_labels(),
        "defaults": get_defaults(),
    }


# --- convenience accessors (used by watchers / overlays) ---


def get_record_stop_hotkey() -> tuple[str, ...]:
    return get_hotkey("record_stop")


def get_record_stop_label() -> str:
    return get_hotkey_label("record_stop")


def set_record_stop_hotkey(keys: Iterable[Any] | None) -> tuple[str, ...]:
    return set_hotkey("record_stop", keys)


def get_start_run_hotkey() -> tuple[str, ...]:
    return get_hotkey("start_run")


def get_start_run_label() -> str:
    return get_hotkey_label("start_run")


def get_stop_run_hotkey() -> tuple[str, ...]:
    return get_hotkey("stop_run")


def get_stop_run_label() -> str:
    return get_hotkey_label("stop_run")


def get_pause_run_hotkey() -> tuple[str, ...]:
    return get_hotkey("pause_run")


def get_pause_run_label() -> str:
    return get_hotkey_label("pause_run")


def record_stop_matches(pressed_name: str, held: set[str]) -> bool:
    """True when `pressed_name` is the trigger and all other combo keys are held."""
    keys = get_record_stop_hotkey()
    if not keys:
        return False
    trigger = keys[-1]
    need = set(keys[:-1])
    if pressed_name != trigger:
        return False
    return need.issubset(held)
