"""系统路径：解析桌面 / 文档 / 下载 / 临时目录等系统特殊文件夹的绝对路径。"""

from __future__ import annotations

from typing import Any

from backend.blocks._os_ops import special_path

PATH_KEYS = [
    "desktop",
    "documents",
    "downloads",
    "pictures",
    "music",
    "videos",
    "startup",
    "recent",
    "temp",
    "appdata_roaming",
    "appdata_local",
    "home",
    "program_files",
    "fonts",
    "windows",
    "exe_dir",
]

PATH_LABELS = {
    "desktop": "桌面",
    "documents": "文档",
    "downloads": "下载",
    "pictures": "图片",
    "music": "音乐",
    "videos": "视频",
    "startup": "开机自启",
    "recent": "最近使用",
    "temp": "临时目录",
    "appdata_roaming": "AppData (Roaming)",
    "appdata_local": "AppData (Local)",
    "home": "用户主目录",
    "program_files": "Program Files",
    "fonts": "字体",
    "windows": "Windows 目录",
    "exe_dir": "应用所在目录",
}

SCHEMA = {
    "type": "sys_path",
    "description": "返回常用系统目录路径（桌面/文档/下载/临时等）。",
    "label": "系统路径",
    "category": "系统类",
    "inputs": [
        {
            "name": "key",
            "type": "select",
            "label": "路径类型",
            "options": PATH_KEYS,
            "default": "desktop",
            "option_labels": PATH_LABELS,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "path", "type": "string"},
        {"name": "exists", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from pathlib import Path

    path, err = special_path(params.get("key"))
    if err or not path:
        return {"ok": False, "path": path or "", "exists": False, "error": err or "路径不可用"}
    try:
        exists = Path(path).exists()
    except Exception:
        exists = False
    return {"ok": True, "path": path, "exists": exists, "error": ""}
