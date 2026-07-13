from __future__ import annotations

from backend.core.input.provider_registry import get_provider_registry
from backend.core.input.resolve import normalize_click_params
from backend.core.input.types import ERROR_INVALID_MODE

SCHEMA = {
    "type": "click",
    "label": "鼠标点击",
    "category": "动作类",
    "inputs": [
        {
            "name": "capture_mode",
            "type": "select",
            "label": "录入模式",
            "options": ["coord", "frida_ui"],
            "default": "coord",
        },
        {"name": "x", "type": "number", "label": "X", "default": 0},
        {"name": "y", "type": "number", "label": "Y", "default": 0},
        {
            "name": "button",
            "type": "select",
            "label": "按键",
            "options": ["left", "right", "middle"],
            "default": "left",
        },
        {
            "name": "click_type",
            "type": "select",
            "label": "点击类型",
            "options": ["single", "double"],
            "default": "single",
        },
        {"name": "move_duration", "type": "number", "label": "移动耗时(ms)", "default": 0},
        {
            "name": "frida_ui",
            "type": "object",
            "label": "Frida UI 目标",
            "default": None,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "button", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    target = normalize_click_params(params)
    registry = get_provider_registry()
    provider_or_err = registry.require_playback(target.capture_mode)
    if isinstance(provider_or_err, dict):
        raise RuntimeError(provider_or_err.get("message") or ERROR_INVALID_MODE)
    ctx = context if isinstance(context, dict) else {}
    result = provider_or_err.execute(target, ctx) or {}
    # Echo resolved coords when provider omits them (e.g. frida_ui).
    if "x" not in result and target.coord is not None:
        result["x"] = int(target.coord.x)
    if "y" not in result and target.coord is not None:
        result["y"] = int(target.coord.y)
    result.setdefault("ok", True)
    result.setdefault("button", target.button or "left")
    return result
