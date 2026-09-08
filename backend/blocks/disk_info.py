"""磁盘空间：查询单个路径所在分区或全部分区的容量与剩余空间。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

SCHEMA = {
    "type": "disk_info",
    "description": "查询各磁盘分区的总容量与剩余空间。",
    "label": "磁盘空间",
    "category": "系统类",
    "inputs": [
        {
            "name": "mode",
            "type": "select",
            "label": "查询方式",
            "options": ["path", "all"],
            "default": "path",
            "option_labels": {"path": "按路径所在分区", "all": "全部分区"},
        },
        {
            "name": "path",
            "type": "string",
            "label": "路径",
            "default": "",
            "placeholder": "留空=系统盘；任意文件/文件夹路径均可",
            "ui": "file_or_dir",
            "bindable": True,
            "show_when": {"mode": "path"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "drive", "type": "string"},
        {"name": "total_gb", "type": "number"},
        {"name": "free_gb", "type": "number"},
        {"name": "used_percent", "type": "number"},
        {
            "name": "drives",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {
                "drive": "string",
                "total_gb": "number",
                "free_gb": "number",
                "used_percent": "number",
            },
        },
        {"name": "count", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}

_EMPTY = {
    "ok": False,
    "drive": "",
    "total_gb": 0,
    "free_gb": 0,
    "used_percent": 0,
    "drives": [],
    "count": 0,
    "error": "",
}


def _usage_for_path(raw_path: str) -> dict[str, Any]:
    text = str(raw_path or "").strip().strip('"')
    if not text:
        text = str(Path.home().anchor) or "C:\\"
    p = Path(text)
    while not p.exists() and p.parent != p:
        p = p.parent
    if not p.exists():
        return {**_EMPTY, "error": f"路径不存在: {text}"}
    try:
        total, used, free = shutil.disk_usage(str(p))
    except Exception as exc:
        return {**_EMPTY, "error": str(exc)}
    percent = round(100.0 * used / total, 1) if total else 0
    return {
        "ok": True,
        "drive": str(p.anchor or p),
        "total_gb": round(total / (1024 ** 3), 2),
        "free_gb": round(free / (1024 ** 3), 2),
        "used_percent": percent,
        "drives": [
            {
                "drive": str(p.anchor or p),
                "total_gb": round(total / (1024 ** 3), 2),
                "free_gb": round(free / (1024 ** 3), 2),
                "used_percent": percent,
            }
        ],
        "count": 1,
        "error": "",
    }


def _usage_all() -> dict[str, Any]:
    import os as _os
    import string

    drives: list[dict[str, Any]] = []
    # Windows 盘符枚举（A-Z），非 Windows 时回退 psutil 常见挂载点
    if _os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            try:
                total, used, free = shutil.disk_usage(root)
            except Exception:
                continue
            percent = round(100.0 * used / total, 1) if total else 0
            drives.append(
                {
                    "drive": root,
                    "total_gb": round(total / (1024 ** 3), 2),
                    "free_gb": round(free / (1024 ** 3), 2),
                    "used_percent": percent,
                }
            )
    if not drives:
        try:
            import psutil

            for part in psutil.disk_partitions(all=False):
                try:
                    total, used, free = shutil.disk_usage(part.mountpoint)
                except Exception:
                    continue
                percent = round(100.0 * used / total, 1) if total else 0
                drives.append(
                    {
                        "drive": part.mountpoint,
                        "total_gb": round(total / (1024 ** 3), 2),
                        "free_gb": round(free / (1024 ** 3), 2),
                        "used_percent": percent,
                    }
                )
        except Exception:
            pass
    if not drives:
        return {**_EMPTY, "error": "未找到可用磁盘分区"}
    return {
        "ok": True,
        "drive": drives[0]["drive"],
        "total_gb": drives[0]["total_gb"],
        "free_gb": drives[0]["free_gb"],
        "used_percent": drives[0]["used_percent"],
        "drives": drives,
        "count": len(drives),
        "error": "",
    }


def handler(params, context, **kwargs):
    mode = str(params.get("mode") or "path").strip().lower()
    if mode == "all":
        return _usage_all()
    return _usage_for_path(params.get("path"))
