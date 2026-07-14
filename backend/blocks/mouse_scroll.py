from __future__ import annotations

import time

import pyautogui

from backend.blocks._helpers import point_looks_unconfigured, require_configured_point, resolve_point

SCHEMA = {
    "type": "mouse_scroll",
    "label": "鼠标滚轮",
    "category": "动作类",
    "inputs": [
        {
            "name": "x",
            "type": "number",
            "label": "焦点X",
            "default": 0,
            "placeholder": "取点后滚动会在此坐标执行",
        },
        {
            "name": "y",
            "type": "number",
            "label": "焦点Y",
            "default": 0,
        },
        {
            "name": "move_first",
            "type": "select",
            "label": "先移到焦点",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {"true": "是（推荐）", "false": "否（当前位置滚）"},
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

    # 已取点则始终滚到该点（避免默认 false 时在 Nexuz 窗口上空滚）。
    move_first = str(params.get("move_first", "true")).lower() == "true"
    configured = not point_looks_unconfigured(params)
    x = y = 0
    if configured or move_first:
        if not configured:
            require_configured_point(params, label="滚轮焦点")
        x, y = resolve_point(params)
        pyautogui.moveTo(x, y)
        time.sleep(0.05)

    def _vscroll(amount: int) -> None:
        if configured or move_first:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)

    def _hscroll(amount: int) -> None:
        if configured or move_first:
            pyautogui.hscroll(amount, x=x, y=y)
        else:
            pyautogui.hscroll(amount)

    if direction == "up":
        _vscroll(clicks)
        amount = clicks
    elif direction == "down":
        _vscroll(-clicks)
        amount = -clicks
    elif direction == "left":
        _hscroll(-clicks)
        amount = -clicks
    elif direction == "right":
        _hscroll(clicks)
        amount = clicks
    else:
        raise ValueError(f"未知滚动方向: {direction}")

    return {"ok": True, "x": x, "y": y, "amount": amount}
