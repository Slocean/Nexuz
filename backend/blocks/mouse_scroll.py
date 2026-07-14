from __future__ import annotations

import pyautogui

from backend.blocks._helpers import require_configured_point, resolve_point

SCHEMA = {
    "type": "mouse_scroll",
    "label": "鼠标滚轮",
    "category": "动作类",
    "inputs": [
        {
            "name": "x",
            "type": "number",
            "label": "焦点X（可选）",
            "default": 0,
            "placeholder": "滚动前移到此坐标",
        },
        {
            "name": "y",
            "type": "number",
            "label": "焦点Y（可选）",
            "default": 0,
        },
        {
            "name": "move_first",
            "type": "select",
            "label": "先移到焦点",
            "options": ["true", "false"],
            "default": "false",
            "option_labels": {"true": "是", "false": "否（当前位置滚）"},
        },
        {
            "name": "direction",
            "type": "select",
            "label": "方向",
            "options": ["up", "down", "left", "right"],
            "default": "down",
            "option_labels": {
                "up": "向上",
                "down": "向下",
                "left": "向左",
                "right": "向右",
            },
        },
        {
            "name": "clicks",
            "type": "number",
            "label": "滚动量",
            "default": 3,
            "placeholder": "滚轮刻度数（越大滚得越多）",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "amount", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    direction = str(params.get("direction") or "down").strip().lower()
    try:
        clicks = abs(int(float(params.get("clicks") or 3)))
    except (TypeError, ValueError):
        clicks = 3
    if clicks <= 0:
        clicks = 1

    # Default: scroll at current cursor — avoid silently jumping to (0,0).
    move_first = str(params.get("move_first", "false")).lower() == "true"
    x = y = 0
    if move_first:
        require_configured_point(params, label="滚轮焦点")
        x, y = resolve_point(params)
        pyautogui.moveTo(x, y)

    if direction == "up":
        pyautogui.scroll(clicks)
        amount = clicks
    elif direction == "down":
        pyautogui.scroll(-clicks)
        amount = -clicks
    elif direction == "left":
        pyautogui.hscroll(-clicks)
        amount = -clicks
    elif direction == "right":
        pyautogui.hscroll(clicks)
        amount = clicks
    else:
        raise ValueError(f"未知滚动方向: {direction}")

    return {"ok": True, "x": x, "y": y, "amount": amount}
