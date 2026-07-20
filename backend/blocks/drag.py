from __future__ import annotations

import pyautogui

from backend.blocks._helpers import resolve_point, require_configured_point

SCHEMA = {
    "type": "drag",
    "label": "鼠标拖拽",
    "category": "动作类",
    "inputs": [
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
        {"name": "from_x", "type": "number", "label": "起点X", "default": 0},
        {"name": "from_y", "type": "number", "label": "起点Y", "default": 0},
        {"name": "to_x", "type": "number", "label": "终点X", "default": 0},
        {"name": "to_y", "type": "number", "label": "终点Y", "default": 0},
        {"name": "duration", "type": "number", "label": "耗时毫秒", "default": 300},
    ],
    "outputs": [
        {"name": "from_x", "type": "number"},
        {"name": "from_y", "type": "number"},
        {"name": "to_x", "type": "number"},
        {"name": "to_y", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    mode = str(params.get("coordinate_mode") or "screen_abs").strip() or "screen_abs"
    shared_target = params.get("window_target")
    from_target = params.get("from_window_target") or shared_target
    to_target = params.get("to_window_target") or shared_target

    require_configured_point(
        {
            "x": params.get("from_x"),
            "y": params.get("from_y"),
            "point_norm": params.get("from_point_norm"),
            "window_target": from_target,
            "coordinate_mode": mode,
        },
        label="拖拽起点",
    )
    require_configured_point(
        {
            "x": params.get("to_x"),
            "y": params.get("to_y"),
            "point_norm": params.get("to_point_norm"),
            "window_target": to_target,
            "coordinate_mode": mode,
        },
        label="拖拽终点",
    )
    fx, fy = resolve_point(
        {
            "x": params.get("from_x"),
            "y": params.get("from_y"),
            "point_norm": params.get("from_point_norm"),
            "coord_space": params.get("coord_space"),
            "coordinate_mode": mode,
            "window_target": from_target,
        }
    )
    tx, ty = resolve_point(
        {
            "x": params.get("to_x"),
            "y": params.get("to_y"),
            "point_norm": params.get("to_point_norm"),
            "coord_space": params.get("coord_space"),
            "coordinate_mode": mode,
            "window_target": to_target,
        }
    )
    duration = float(params.get("duration", 300) or 0) / 1000.0
    from backend.core.host_window import yield_host_mouse

    with yield_host_mouse():
        pyautogui.moveTo(fx, fy)
        pyautogui.dragTo(tx, ty, duration=duration, button="left")
    return {"from_x": fx, "from_y": fy, "to_x": tx, "to_y": ty}
