from __future__ import annotations

import pyautogui

from backend.blocks._helpers import resolve_point

SCHEMA = {
    "type": "click",
    "label": "鼠标点击",
    "category": "动作类",
    "inputs": [
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
    ],
    "outputs": [],
}


def handler(params, context, **kwargs):
    x, y = resolve_point(params)
    button = params.get("button", "left")
    click_type = params.get("click_type", "single")
    move_duration = float(params.get("move_duration", 0) or 0) / 1000.0
    clicks = 2 if click_type == "double" else 1
    if move_duration > 0:
        pyautogui.moveTo(x, y, duration=move_duration)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=0.05)
    return {}
