from __future__ import annotations

from backend.blocks._system_io import clipboard_read, clipboard_write

SCHEMA = {
    "type": "clipboard",
    "label": "剪贴板",
    "category": "系统类",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "操作",
            "options": ["read", "write"],
            "default": "write",
            "option_labels": {"read": "读取", "write": "写入"},
        },
        {
            "name": "text",
            "type": "string",
            "label": "文本",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"action": "write"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "text", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    action = str(params.get("action") or "write").strip().lower()
    if action == "read":
        res = clipboard_read()
        return {
            "ok": bool(res.get("ok")),
            "text": res.get("text") or "",
            "error": res.get("error") or "",
        }

    text = "" if params.get("text") is None else str(params.get("text"))
    res = clipboard_write(text)
    return {
        "ok": bool(res.get("ok")),
        "text": res.get("text") if res.get("ok") else text,
        "error": res.get("error") or "",
    }
