"""进程列表：枚举本机运行中的进程（按内存排序），支持按名称过滤。

输出 pids / names 便于绑定到「结束进程」，items 为完整明细。
"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import list_processes

SCHEMA = {
    "type": "process_list",
    "label": "进程列表",
    "category": "系统类",
    "inputs": [
        {
            "name": "name_filter",
            "type": "string",
            "label": "按名称过滤",
            "default": "",
            "placeholder": "留空=全部进程；填 notepad 匹配 notepad.exe",
            "bindable": True,
        },
        {
            "name": "limit",
            "type": "number",
            "label": "返回条数上限",
            "default": 200,
            "placeholder": "0=不限（全量可能上千条）",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "count", "type": "number"},
        {"name": "total", "type": "number"},
        {"name": "pids", "type": "array", "itemType": "number", "canvas": False},
        {"name": "names", "type": "array", "itemType": "string", "canvas": False},
        {
            "name": "items",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {"pid": "number", "name": "string", "mem_mb": "number"},
        },
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    try:
        limit = int(float(params.get("limit") if params.get("limit") not in (None, "") else 200))
    except (TypeError, ValueError):
        limit = 200
    res = list_processes(str(params.get("name_filter") or ""), limit)
    if res.get("error"):
        return {
            "ok": False,
            "count": 0,
            "total": 0,
            "pids": [],
            "names": [],
            "items": [],
            "error": str(res.get("error")),
        }
    items = res.get("items") or []
    return {
        "ok": True,
        "count": len(items),
        "total": int(res.get("filtered") or 0),
        "pids": [item.get("pid") for item in items],
        "names": [item.get("name") for item in items],
        "items": items,
        "error": "",
    }
