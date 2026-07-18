from __future__ import annotations

from backend.blocks._window_ops import MATCH_INPUTS, match_or_error
from backend.core import window_coords as wc

SCHEMA = {
    "type": "window_close",
    "label": "关闭窗口",
    "category": "系统类",
    "inputs": [
        *MATCH_INPUTS,
        {
            "name": "force",
            "type": "select",
            "label": "强制结束进程",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否（发送关闭消息）", "true": "是（TerminateProcess）"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "title", "type": "string"},
        {"name": "pid", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    hwnd, info, err = match_or_error(params)
    if not hwnd:
        return {
            "ok": False,
            "title": "",
            "pid": 0,
            "error": err or "未找到窗口",
        }
    force = str(params.get("force") or "false").strip().lower() in ("true", "1", "yes")
    try:
        wc.close_hwnd(hwnd, force=force)
    except Exception as exc:
        return {
            "ok": False,
            "title": str(info.get("title") or ""),
            "pid": int(info.get("pid") or 0),
            "error": str(exc),
        }
    return {
        "ok": True,
        "title": str(info.get("title") or ""),
        "pid": int(info.get("pid") or 0),
        "error": "",
    }
