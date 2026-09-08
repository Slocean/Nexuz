"""电源操作：锁屏 / 息屏 / 睡眠 / 休眠 / 关机 / 重启 / 取消关机。

关机与重启走系统 shutdown 命令并默认延迟 60 秒（配合「取消关机」可反悔），
其余动作为即时执行。流程策略层面归入高权限积木。
"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import (
    lock_workstation,
    monitor_off,
    shutdown_command,
    suspend_system,
)

ACTIONS = ["lock", "screen_off", "sleep", "hibernate", "shutdown", "restart", "cancel_shutdown"]

ACTION_LABELS = {
    "lock": "锁屏",
    "screen_off": "关闭显示器",
    "sleep": "睡眠",
    "hibernate": "休眠",
    "shutdown": "关机",
    "restart": "重启",
    "cancel_shutdown": "取消已计划的关机/重启",
}

SCHEMA = {
    "type": "power_action",
    "description": "关机/重启/睡眠等电源操作（高危：AI 与外部流程默认禁止）。",
    "label": "电源操作",
    "category": "系统类",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "动作",
            "options": ACTIONS,
            "default": "lock",
            "option_labels": ACTION_LABELS,
        },
        {
            "name": "delay_sec",
            "type": "number",
            "label": "关机/重启延迟秒",
            "default": 60,
            "placeholder": "延迟期间可用「取消关机」反悔",
            "show_when": {"action": ["shutdown", "restart"]},
        },
        {
            "name": "force",
            "type": "select",
            "label": "强制关闭应用",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否（未保存会提示）", "true": "是（不保存直接关）"},
            "show_when": {"action": ["shutdown", "restart"]},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "action", "type": "string"},
        {"name": "message", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    action = str(params.get("action") or "lock").strip().lower()
    try:
        delay = int(float(params.get("delay_sec") if params.get("delay_sec") not in (None, "") else 60))
    except (TypeError, ValueError):
        delay = 60
    delay = max(0, min(delay, 315360000))
    force = str(params.get("force") or "false").strip().lower() in ("true", "1", "yes")

    if action == "lock":
        ok, err = lock_workstation()
    elif action == "screen_off":
        ok, err = monitor_off()
    elif action == "sleep":
        ok, err = suspend_system(hibernate=False)
    elif action == "hibernate":
        ok, err = suspend_system(hibernate=True)
    elif action == "shutdown":
        ok, err = shutdown_command("shutdown", delay, force)
    elif action == "restart":
        ok, err = shutdown_command("restart", delay, force)
    elif action == "cancel_shutdown":
        ok, err = shutdown_command("cancel", 0, False)
    else:
        ok, err = False, f"未知动作: {action}"

    message = ""
    if ok:
        if action in ("shutdown", "restart"):
            message = f"已计划{'关机' if action == 'shutdown' else '重启'}（{delay} 秒后）"
        elif action == "cancel_shutdown":
            message = "已取消计划的关机/重启"
        else:
            message = ACTION_LABELS.get(action, action) + "已执行"
    return {"ok": ok, "action": action, "message": message, "error": err}
