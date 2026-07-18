from __future__ import annotations

import time

from backend.blocks._helpers import interruptible_sleep
from backend.blocks._window_ops import MATCH_INPUTS, match_or_error
from backend.core import window_coords as wc

SCHEMA = {
    "type": "window_wait",
    "label": "等待窗口",
    "category": "系统类",
    "inputs": [
        *MATCH_INPUTS,
        {
            "name": "timeout_sec",
            "type": "number",
            "label": "超时秒数",
            "default": 30,
        },
        {
            "name": "poll_ms",
            "type": "number",
            "label": "轮询间隔毫秒",
            "default": 200,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "found", "type": "boolean"},
        {"name": "title", "type": "string"},
        {"name": "pid", "type": "number"},
        {"name": "process_name", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    criteria = wc.criteria_from_params(params)
    if not wc._supported():
        return {
            "ok": False,
            "found": False,
            "title": "",
            "pid": 0,
            "process_name": "",
            "error": "窗口操作仅支持 Windows",
        }
    if not wc.criteria_has_match_fields(criteria):
        return {
            "ok": False,
            "found": False,
            "title": "",
            "pid": 0,
            "process_name": "",
            "error": "请至少填写标题、进程名或类名之一",
        }

    try:
        timeout = max(0.0, float(params.get("timeout_sec") if params.get("timeout_sec") is not None else 30))
    except (TypeError, ValueError):
        timeout = 30.0
    try:
        poll_ms = max(50, int(float(params.get("poll_ms") if params.get("poll_ms") is not None else 200)))
    except (TypeError, ValueError):
        poll_ms = 200

    deadline = time.monotonic() + timeout
    last_error = "等待超时"
    while True:
        hwnd, info, err = match_or_error(params)
        if hwnd:
            return {
                "ok": True,
                "found": True,
                "title": str(info.get("title") or ""),
                "pid": int(info.get("pid") or 0),
                "process_name": str(info.get("process_name") or ""),
                "error": "",
            }
        last_error = err or last_error
        if time.monotonic() >= deadline:
            break
        try:
            interruptible_sleep(poll_ms / 1000.0, should_stop, cooperate=cooperate)
        except InterruptedError:
            return {
                "ok": False,
                "found": False,
                "title": "",
                "pid": 0,
                "process_name": "",
                "error": "流程已停止",
            }

    return {
        "ok": False,
        "found": False,
        "title": "",
        "pid": 0,
        "process_name": "",
        "error": f"等待超时（{timeout:g}s）：{last_error}",
    }
