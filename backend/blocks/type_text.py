from __future__ import annotations

import sys

if sys.platform != "win32":
    try:  # 无桌面环境（无头 Linux）导入会炸；真机积木由 requires 闸拒绝
        import pyautogui
    except Exception:
        pyautogui = None
else:
    import pyautogui

SCHEMA = {
    "type": "type_text",
    "requires": "desktop",
    "description": "模拟键盘输入一段文本。",
    "label": "输入文本",
    "category": "动作类",
    "inputs": [
        {"name": "text", "type": "string", "label": "文本", "default": ""},
        {"name": "interval", "type": "number", "label": "字符间隔毫秒", "default": 0},
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
