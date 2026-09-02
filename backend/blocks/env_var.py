"""环境变量：读取 / 列出 / 设置环境变量。

set 只修改本应用进程的环境（含后续「执行命令」子进程继承），不改系统注册表，
应用退出即失效，对系统无持久影响。
"""

from __future__ import annotations

import os
from typing import Any

SCHEMA = {
    "type": "env_var",
    "label": "环境变量",
    "category": "系统类",
    "inputs": [
        {
            "name": "action",
            "type": "select",
            "label": "操作",
            "options": ["get", "list", "set"],
            "default": "get",
            "option_labels": {"get": "读取", "list": "列出全部", "set": "设置"},
        },
        {
            "name": "name",
            "type": "string",
            "label": "变量名",
            "default": "PATH",
            "bindable": True,
            "show_when": {"action": ["get", "set"]},
        },
        {
            "name": "value",
            "type": "string",
            "label": "值",
            "default": "",
            "ui": "textarea",
            "bindable": True,
            "show_when": {"action": "set"},
        },
        {
            "name": "prefix",
            "type": "string",
            "label": "按前缀过滤",
            "default": "",
            "placeholder": "留空=全部；如 NEXUZ_",
            "bindable": True,
            "show_when": {"action": "list"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "value", "type": "string"},
        {"name": "exists", "type": "boolean"},
        {"name": "keys", "type": "array", "itemType": "string", "canvas": False},
        {"name": "count", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    action = str(params.get("action") or "get").strip().lower()
    name = str(params.get("name") or "").strip()

    if action == "get":
        if not name:
            return {"ok": False, "value": "", "exists": False, "keys": [], "count": 0, "error": "变量名不能为空"}
        value = os.environ.get(name)
        return {
            "ok": True,
            "value": "" if value is None else str(value),
            "exists": value is not None,
            "keys": [],
            "count": 0,
            "error": "" if value is not None else f"环境变量不存在: {name}",
        }

    if action == "set":
        if not name:
            return {"ok": False, "value": "", "exists": False, "keys": [], "count": 0, "error": "变量名不能为空"}
        value = "" if params.get("value") is None else str(params.get("value"))
        os.environ[name] = value
        return {"ok": True, "value": value, "exists": True, "keys": [], "count": 0, "error": ""}

    if action == "list":
        prefix = str(params.get("prefix") or "").strip()
        keys = sorted(k for k in os.environ if not prefix or k.upper().startswith(prefix.upper()))
        return {"ok": True, "value": "", "exists": False, "keys": keys, "count": len(keys), "error": ""}

    return {"ok": False, "value": "", "exists": False, "keys": [], "count": 0, "error": f"未知操作: {action}"}
