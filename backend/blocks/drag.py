from __future__ import annotations

import pyautogui

from backend.blocks._helpers import validate_point

SCHEMA = {
    "type": "drag",
    "label": "鼠标拖拽",
    "category": "动作类",
    "inputs": [
        {"name": "from_x", "type": "number", "label": "起点X", "default": 0},
        {"name": "from_y", "type": "number", "label": "起点Y", "default": 0},
        {"name": "to_x", "type": "number", "label": "终点X", "default": 0},
        {"name": "to_y", "type": "number", "label": "终点Y", "default": 0},
        {"name": "duration", "type": "number", "label": "耗时(ms)", "default": 300},
    ],
    "outputs": [],
}


def handler(params, context, **kwargs):
    fx, fy = int(params.get("from_x", 0)), int(params.get("from_y", 0))
    tx, ty = int(params.get("to_x", 0)), int(params.get("to_y", 0))
    validate_point(fx, fy)
    validate_point(tx, ty)
    duration = float(params.get("duration", 300) or 0) / 1000.0
    pyautogui.moveTo(fx, fy)
    pyautogui.dragTo(tx, ty, duration=duration, button="left")
    return {}
