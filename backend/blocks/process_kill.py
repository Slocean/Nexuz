"""结束进程：按 PID 或进程名终止进程。

系统关键进程（System/lsass/csrss 等）与本应用自身一律拒绝，防误杀蓝屏。
按名称匹配时同时命中 xxx 与 xxx.exe。
"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import kill_processes

SCHEMA = {
    "type": "process_kill",
    "description": "按 PID 或进程名结束进程。",
    "label": "结束进程",
    "category": "系统类",
    "done_log": "已结束 {{killed_count}} 个进程",
    "inputs": [
        {
            "name": "target_mode",
            "type": "select",
            "label": "定位方式",
            "options": ["pid", "name"],
            "default": "name",
            "option_labels": {"pid": "按 PID", "name": "按进程名"},
        },
        {
            "name": "pid",
            "type": "number",
            "label": "进程 PID",
            "default": 0,
            "show_when": {"target_mode": "pid"},
            "bindable": True,
        },
        {
            "name": "name",
            "type": "string",
            "label": "进程名",
            "default": "",
            "placeholder": "如 notepad 或 notepad.exe，会结束全部同名进程",
            "show_when": {"target_mode": "name"},
            "bindable": True,
        },
        {
            "name": "force",
            "type": "select",
            "label": "强制结束",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否（请求退出，等 3 秒）", "true": "是（无响应时强杀）"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "killed_count", "type": "number"},
        {"name": "killed_pids", "type": "array", "itemType": "number", "canvas": False},
        {
            "name": "refused",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {"pid": "number", "name": "string", "reason": "string"},
        },
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    mode = str(params.get("target_mode") or "name").strip().lower()
    force = str(params.get("force") or "false").strip().lower() in ("true", "1", "yes")

    pid = 0
    name = ""
    if mode == "pid":
        try:
            pid = int(float(params.get("pid") or 0))
        except (TypeError, ValueError):
            return {
                "ok": False,
                "killed_count": 0,
                "killed_pids": [],
                "refused": [],
                "error": "PID 必须是数字",
            }
        if pid <= 0:
            return {
                "ok": False,
                "killed_count": 0,
                "killed_pids": [],
                "refused": [],
                "error": "请填写有效的进程 PID",
            }
    else:
        name = str(params.get("name") or "").strip()
        if not name:
            return {
                "ok": False,
                "killed_count": 0,
                "killed_pids": [],
                "refused": [],
                "error": "请填写进程名",
            }

    res = kill_processes(pid if pid else None, name, force)
    killed = res.get("killed") or []
    refused = res.get("refused") or []
    error = str(res.get("error") or "")
    ok = bool(killed) and not refused
    # 部分成功（有 refused 明细）也算失败，提示用户可开强制或权限不足
    if killed and refused:
        error = error or f"有 {len(refused)} 个目标未能结束"
    if not killed and not refused and not error:
        error = f"未找到进程: {pid if mode == 'pid' else name}"
    return {
        "ok": ok,
        "killed_count": len(killed),
        "killed_pids": killed,
        "refused": refused,
        "error": error,
    }
