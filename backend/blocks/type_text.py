from __future__ import annotations

import pyautogui

SCHEMA = {
    "type": "type_text",
    "label": "输入文本",
    "category": "动作类",
    "inputs": [
        {"name": "text", "type": "string", "label": "文本", "default": ""},
        {"name": "interval", "type": "number", "label": "字符间隔(ms)", "default": 0},
    ],
    "outputs": [],
}


def handler(params, context, **kwargs):
    text = str(params.get("text", ""))
    interval = float(params.get("interval", 0) or 0) / 1000.0
    # pyautogui.typewrite does not support Chinese well; use write for unicode when possible
    try:
        pyautogui.write(text, interval=interval)
    except Exception:
        pyautogui.typewrite(text, interval=interval)
    return {}
