"""音量控制：通过系统音量媒体键调节音量（增 / 减 / 静音切换）。

走 Windows 标准音量键事件，对所有应用生效；1 步 ≈ 2% 音量。
"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import (
    VK_VOLUME_DOWN,
    VK_VOLUME_MUTE,
    VK_VOLUME_UP,
    send_volume_key,
)

SCHEMA = {
    "type": "volume_action",
    "label": "音量控制",
    "category": "系统类",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "动作",
            "options": ["up", "down", "toggle_mute"],
            "default": "up",
            "option_labels": {"up": "增大音量", "down": "减小音量", "toggle_mute": "静音/取消静音"},
        },
        {
            "name": "steps",
            "type": "number",
            "label": "步数",
            "default": 5,
            "placeholder": "1 步 ≈ 2% 音量；静音切换忽略此参数",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "action", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    action = str(params.get("action") or "up").strip().lower()
    try:
        steps = int(float(params.get("steps") if params.get("steps") not in (None, "") else 5))
    except (TypeError, ValueError):
        steps = 5
    steps = max(1, min(steps, 50))

    if action == "up":
        ok, err = send_volume_key(VK_VOLUME_UP, steps)
    elif action == "down":
        ok, err = send_volume_key(VK_VOLUME_DOWN, steps)
    elif action == "toggle_mute":
        ok, err = send_volume_key(VK_VOLUME_MUTE, 1)
    else:
        ok, err = False, f"未知动作: {action}"
    return {"ok": ok, "action": action, "error": err}
