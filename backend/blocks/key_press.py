from __future__ import annotations

import pyautogui

from backend.blocks._helpers import interruptible_sleep

SCHEMA = {
    "type": "key_press",
    "label": "按键",
    "category": "动作类",
    "inputs": [
        {
            "name": "key_mode",
            "type": "select",
            "label": "模式",
            "options": ["single", "sequence"],
            "default": "single",
            "option_labels": {"single": "单次", "sequence": "序列"},
        },
        {
            "name": "keys",
            "type": "keys",
            "label": "按键",
            "default": ["enter"],
            "placeholder": "ctrl+c",
            "show_when": {"key_mode": "single"},
        },
        {
            "name": "steps",
            "type": "key_steps",
            "label": "按键序列",
            "default": [],
            "bindable": False,
            "show_when": {"key_mode": "sequence"},
        },
        {
            "name": "interval_ms",
            "type": "number",
            "label": "步间延迟毫秒",
            "default": 100,
            "show_when": {"key_mode": "sequence"},
            "placeholder": "相邻两步间隔",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "count", "type": "number"},
    ],
}


def _parse_keys(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(k).strip() for k in raw if str(k).strip()]
    if isinstance(raw, str):
        return [k.strip() for k in raw.split("+") if k.strip()]
    return []


def _press(keys: list[str]) -> None:
    if not keys:
        raise ValueError("按键不能为空")
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)


def _as_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    mode = str(params.get("key_mode") or "single").strip() or "single"

    if mode != "sequence":
        keys = _parse_keys(params.get("keys"))
        _press(keys)
        return {"ok": True, "count": 1}

    steps = params.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise ValueError("序列模式请至少添加一步按键")

    interval = max(0, _as_int(params.get("interval_ms"), 100))
    done = 0
    for i, step in enumerate(steps):
        if i > 0:
            if isinstance(step, dict):
                delay = step.get("delay_ms")
                wait = (
                    _as_int(delay, interval)
                    if delay is not None and delay != ""
                    else interval
                )
            else:
                wait = interval
            if wait > 0:
                interruptible_sleep(wait / 1000.0, should_stop, cooperate=cooperate)
        keys = _parse_keys(step.get("keys") if isinstance(step, dict) else step)
        _press(keys)
        done += 1

    return {"ok": True, "count": done}
