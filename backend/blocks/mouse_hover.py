from __future__ import annotations

import pyautogui

from backend.blocks._helpers import (
    interruptible_sleep,
    require_configured_point,
    resolve_point,
    sleep_pre_step,
)

SCHEMA = {
    "type": "mouse_hover",
    "label": "鼠标悬停",
    "category": "动作类",
    "inputs": [
        {
            "name": "hover_mode",
            "type": "select",
            "label": "模式",
            "options": ["single", "multi"],
            "default": "single",
            "option_labels": {"single": "单点", "multi": "多点"},
        },
        {
            "name": "coordinate_mode",
            "type": "select",
            "label": "坐标基准",
            "options": ["screen_abs", "window_client", "virtual_norm"],
            "default": "window_client",
            "option_labels": {
                "screen_abs": "屏幕绝对坐标",
                "window_client": "目标窗口相对（推荐）",
                "virtual_norm": "虚拟桌面比例",
            },
        },
        {
            "name": "x",
            "type": "number",
            "label": "X",
            "default": 0,
            "show_when": {"hover_mode": "single"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "Y",
            "default": 0,
            "show_when": {"hover_mode": "single"},
        },
        {
            "name": "points",
            "type": "point_list",
            "label": "悬停点",
            "default": [],
            "bindable": False,
            "show_when": {"hover_mode": "multi"},
        },
        {
            "name": "interval_ms",
            "type": "number",
            "label": "点间延迟毫秒",
            "default": 200,
            "show_when": {"hover_mode": "multi"},
            "placeholder": "相邻两点间隔",
        },
        {
            "name": "move_duration",
            "type": "number",
            "label": "移动耗时毫秒",
            "default": 0,
        },
        {
            "name": "hold_ms",
            "type": "number",
            "label": "悬停毫秒",
            "default": 300,
            "placeholder": "到达后停留",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "count", "type": "number"},
    ],
}


def _as_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _hover_at(
    params: dict,
    *,
    hold_ms: int,
    move_duration: float,
    should_stop=None,
    cooperate=None,
) -> tuple[int, int]:
    require_configured_point(params, label="悬停坐标")
    x, y = resolve_point(params)
    from backend.core.host_window import yield_host_mouse

    with yield_host_mouse():
        pyautogui.moveTo(x, y, duration=max(0.0, move_duration))
    if hold_ms > 0:
        interruptible_sleep(hold_ms / 1000.0, should_stop, cooperate=cooperate)
    return x, y


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    mode = str(params.get("hover_mode") or "single").strip() or "single"
    move_duration = float(params.get("move_duration") or 0) / 1000.0
    hold_default = max(0, _as_int(params.get("hold_ms"), 300))

    if mode != "multi":
        x, y = _hover_at(
            params,
            hold_ms=hold_default,
            move_duration=move_duration,
            should_stop=should_stop,
            cooperate=cooperate,
        )
        return {"ok": True, "x": x, "y": y, "count": 1}

    raw_points = params.get("points") or []
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("多点模式请至少添加一个悬停点")

    interval = max(0, _as_int(params.get("interval_ms"), 200))
    last_x, last_y = 0, 0
    done = 0
    window_activated = False

    for i, pt in enumerate(raw_points):
        if not isinstance(pt, dict):
            continue
        sleep_pre_step(
            i,
            pt.get("delay_ms"),
            default_interval=interval,
            should_stop=should_stop,
            cooperate=cooperate,
        )
        hold = pt.get("hold_ms")
        hold_ms = (
            _as_int(hold, hold_default)
            if hold is not None and hold != ""
            else hold_default
        )
        one = {
            "x": pt.get("x", 0),
            "y": pt.get("y", 0),
            "coordinate_mode": params.get("coordinate_mode")
            or pt.get("coordinate_mode")
            or "screen_abs",
            "point_norm": pt.get("point_norm"),
            "coord_space": pt.get("coord_space") or params.get("coord_space"),
            "window_target": pt.get("window_target") or params.get("window_target"),
        }
        if str(one.get("coordinate_mode") or "") == "window_client":
            if window_activated:
                one["activate_window"] = False
            else:
                one["activate_window"] = True
                window_activated = True
        last_x, last_y = _hover_at(
            one,
            hold_ms=hold_ms,
            move_duration=move_duration,
            should_stop=should_stop,
            cooperate=cooperate,
        )
        done += 1

    if done <= 0:
        raise ValueError("多点模式请至少添加一个悬停点")
    return {"ok": True, "x": last_x, "y": last_y, "count": done}
