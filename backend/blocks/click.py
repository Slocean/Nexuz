from __future__ import annotations

from backend.blocks._helpers import interruptible_sleep
from backend.core.input.provider_registry import get_provider_registry
from backend.core.input.resolve import normalize_click_params
from backend.core.input.types import ERROR_INVALID_MODE

SCHEMA = {
    "type": "click",
    "label": "鼠标点击",
    "category": "动作类",
    "inputs": [
        {
            "name": "click_mode",
            "type": "select",
            "label": "模式",
            "options": ["single", "multi"],
            "default": "single",
            "option_labels": {"single": "单点", "multi": "多点"},
        },
        {
            "name": "capture_mode",
            "type": "select",
            "label": "录入模式",
            "options": ["coord", "frida_ui"],
            "default": "coord",
        },
        {
            "name": "x",
            "type": "number",
            "label": "X",
            "default": 0,
            "show_when": {"click_mode": "single"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "Y",
            "default": 0,
            "show_when": {"click_mode": "single"},
        },
        {
            "name": "points",
            "type": "point_list",
            "label": "点击点",
            "default": [],
            "bindable": False,
            "show_when": {"click_mode": "multi"},
        },
        {
            "name": "interval_ms",
            "type": "number",
            "label": "点间延迟毫秒",
            "default": 200,
            "show_when": {"click_mode": "multi"},
            "placeholder": "相邻两点间隔",
        },
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
        {
            "name": "move_duration",
            "type": "number",
            "label": "移动耗时毫秒",
            "default": 0,
            "show_when": {"click_mode": "single"},
        },
        {
            "name": "frida_ui",
            "type": "object",
            "label": "Frida UI 目标",
            "default": None,
            "show_when": {"click_mode": "single"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "button", "type": "string"},
        {"name": "count", "type": "number"},
    ],
}


def _click_once(params: dict, context: dict) -> dict:
    target = normalize_click_params(params)
    registry = get_provider_registry()
    provider_or_err = registry.require_playback(target.capture_mode)
    if isinstance(provider_or_err, dict):
        raise RuntimeError(provider_or_err.get("message") or ERROR_INVALID_MODE)
    result = provider_or_err.execute(target, context) or {}
    if "x" not in result and target.coord is not None:
        result["x"] = int(target.coord.x)
    if "y" not in result and target.coord is not None:
        result["y"] = int(target.coord.y)
    result.setdefault("ok", True)
    result.setdefault("button", target.button or "left")
    return result


def _as_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _point_to_click_params(pt: dict, base: dict) -> dict:
    """Build one click params from a multi-point entry + shared node params."""
    button = base.get("button") or "left"
    click_type = base.get("click_type") or "single"
    frida = pt.get("frida_ui") if isinstance(pt.get("frida_ui"), dict) else None
    if frida and frida.get("hierarchy_path"):
        return {
            "capture_mode": "frida_ui",
            "frida_ui": frida,
            "button": pt.get("button") or button,
            "click_type": click_type,
            "move_duration": 0,
            "x": _as_int(pt.get("x"), 0),
            "y": _as_int(pt.get("y"), 0),
        }
    return {
        "capture_mode": "coord",
        "x": pt.get("x", 0),
        "y": pt.get("y", 0),
        "point_norm": pt.get("point_norm"),
        "coord_space": pt.get("coord_space") or base.get("coord_space"),
        "button": pt.get("button") or button,
        "click_type": click_type,
        "move_duration": 0,
    }


def handler(params, context, should_stop=None, **kwargs):
    ctx = context if isinstance(context, dict) else {}
    mode = str(params.get("click_mode") or "single").strip() or "single"

    if mode != "multi":
        out = _click_once(params, ctx)
        out["count"] = 1
        return out

    raw_points = params.get("points") or []
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("多点模式请至少添加一个点击点")

    interval = max(0, _as_int(params.get("interval_ms"), 200))
    button = params.get("button") or "left"
    last: dict = {"ok": True, "x": 0, "y": 0, "button": button}
    done = 0

    for i, pt in enumerate(raw_points):
        if not isinstance(pt, dict):
            continue
        if i > 0:
            delay = pt.get("delay_ms")
            wait = _as_int(delay, interval) if delay is not None and delay != "" else interval
            if wait > 0:
                interruptible_sleep(wait / 1000.0, should_stop)
        one = _point_to_click_params(pt, params)
        # Prefer node-level capture_mode when point has no frida target
        node_cap = str(params.get("capture_mode") or "coord")
        if node_cap == "frida_ui" and not (
            isinstance(pt.get("frida_ui"), dict) and pt["frida_ui"].get("hierarchy_path")
        ):
            raise ValueError(
                f"多点 #{i + 1} 为 Frida 模式但未录入 UI 目标，请对该点点击「录入」"
            )
        if node_cap == "coord":
            one["capture_mode"] = "coord"
            one.pop("frida_ui", None)
        last = _click_once(one, ctx)
        done += 1

    last["count"] = done
    last.setdefault("ok", True)
    last.setdefault("button", button)
    return last
