from __future__ import annotations

from backend.blocks._system_io import normalize_path, read_text_file, write_text_file

SCHEMA = {
    "type": "file_io",
    "label": "文件读写",
    "category": "系统类",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "操作",
            "options": ["read", "write", "append"],
            "default": "read",
            "option_labels": {"read": "读取", "write": "写入", "append": "追加"},
        },
        {
            "name": "path",
            "type": "string",
            "label": "文件路径",
            "default": "",
            "placeholder": "手动输入，或点「浏览」选择",
            "ui": "file_path",
            "bindable": True,
        },
        {
            "name": "content",
            "type": "string",
            "label": "内容",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"action": ["write", "append"]},
        },
        {
            "name": "encoding",
            "type": "string",
            "label": "编码",
            "default": "utf-8",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "content", "type": "string"},
        {"name": "path", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    action = str(params.get("action") or "read").strip().lower()
    # textarea may wrap long paths — strip whitespace/newlines before resolve
    raw_path = "".join(str(params.get("path") or "").split())
    path, err = normalize_path(raw_path)
    if err or path is None:
        return {"ok": False, "content": "", "path": raw_path or str(params.get("path") or ""), "error": err or "无效路径"}

    encoding = str(params.get("encoding") or "utf-8").strip() or "utf-8"
    if action == "read":
        res = read_text_file(path, encoding=encoding)
        return {
            "ok": bool(res.get("ok")),
            "content": res.get("content") or "",
            "path": res.get("path") or str(path),
            "error": res.get("error") or "",
        }

    content = "" if params.get("content") is None else str(params.get("content"))
    append = action == "append"
    if action not in ("write", "append"):
        return {
            "ok": False,
            "content": "",
            "path": str(path),
            "error": f"未知操作: {action}",
        }
    res = write_text_file(path, content, encoding=encoding, append=append)
    return {
        "ok": bool(res.get("ok")),
        "content": content if res.get("ok") else "",
        "path": res.get("path") or str(path),
        "error": res.get("error") or "",
    }
