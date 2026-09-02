"""打开路径/网址：用系统默认方式打开文件 / 文件夹 / 网址（等价于双击）。"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import open_target

SCHEMA = {
    "type": "open_path",
    "label": "打开路径/网址",
    "category": "系统类",
    "inputs": [
        {
            "name": "target",
            "type": "string",
            "label": "文件 / 文件夹 / 网址",
            "default": "",
            "placeholder": "如 D:\\报表.xlsx、D:\\资料夹、https://example.com",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "show_in_explorer",
            "type": "select",
            "label": "打开方式",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "直接打开（默认程序）", "true": "在资源管理器中定位"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "resolved", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    show = str(params.get("show_in_explorer") or "false").strip().lower() in ("true", "1", "yes")
    target = str(params.get("target") or "")
    ok, resolved, err = open_target(target, show_in_explorer=show)
    return {"ok": ok, "resolved": resolved, "error": err}
