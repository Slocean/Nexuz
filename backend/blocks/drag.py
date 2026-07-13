from __future__ import annotations

import pyautogui

from backend.blocks._helpers import resolve_point

SCHEMA = {
    "type": "drag",
    "label": "鼠标拖拽",
    "category": "动作类",
    "inputs": [
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
    fx, fy = resolve_point(
        {
            "x": params.get("from_x"),
            "y": params.get("from_y"),
            "point_norm": params.get("from_point_norm"),
            "coord_space": params.get("coord_space"),
        }
    )
    tx, ty = resolve_point(
        {
            "x": params.get("to_x"),
            "y": params.get("to_y"),
            "point_norm": params.get("to_point_norm"),
            "coord_space": params.get("coord_space"),
        }
    )
    duration = float(params.get("duration", 300) or 0) / 1000.0
    pyautogui.moveTo(fx, fy)
    pyautogui.dragTo(tx, ty, duration=duration, button="left")
    return {"from_x": fx, "from_y": fy, "to_x": tx, "to_y": ty}
