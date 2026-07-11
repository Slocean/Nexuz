from __future__ import annotations

import pyautogui

SCHEMA = {
    "type": "key_press",
    "label": "按键",
    "category": "动作类",
    "inputs": [
        {
            "name": "keys",
            "type": "keys",
            "label": "按键(组合)",
            "default": ["enter"],
        }
    ],
    "outputs": [],
}


def handler(params, context, **kwargs):
    keys = params.get("keys") or []
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split("+") if k.strip()]
    if not keys:
        raise ValueError("keys 不能为空")
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return {}
