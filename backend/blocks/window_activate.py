from __future__ import annotations

from backend.blocks._window_ops import MATCH_INPUTS, match_or_error
from backend.core import window_coords as wc

SCHEMA = {
    "type": "window_activate",
    "label": "激活窗口",
    "category": "系统类",
    "inputs": [*MATCH_INPUTS],
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
    try:
        wc.activate_hwnd(hwnd)
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
