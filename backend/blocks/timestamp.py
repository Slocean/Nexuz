"""时间戳：输出当前时间的 Unix 时间戳、ISO 时间与自定义格式字符串。

格式用 strftime 语法（%Y 年 %m 月 %d 日 %H 时 %M 分 %S 秒），留空取默认
「2026-01-02 15:04:05」样式，常用于日志命名、文件名时间后缀。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_FORMAT = "%Y-%m-%d %H:%M:%S"

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SCHEMA = {
    "type": "timestamp",
    "label": "时间戳",
    "category": "系统类",
    "done_log": "当前时间：{{local}}",
    "inputs": [
        {
            "name": "format",
            "type": "string",
            "label": "自定义格式",
            "default": DEFAULT_FORMAT,
            "placeholder": "strftime 语法，如 %Y%m%d_%H%M%S",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "timestamp", "type": "number"},
        {"name": "timestamp_ms", "type": "number"},
        {"name": "iso_utc", "type": "string"},
        {"name": "local", "type": "string"},
        {"name": "formatted", "type": "string"},
        {"name": "date", "type": "string"},
        {"name": "time", "type": "string"},
        {"name": "weekday", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    try:
        now = datetime.now()
        fmt = str(params.get("format") or "").strip() or DEFAULT_FORMAT
        try:
            formatted = now.strftime(fmt)
        except (ValueError, TypeError) as exc:
            return {
                "ok": False,
                "timestamp": 0,
                "timestamp_ms": 0,
                "iso_utc": "",
                "local": "",
                "formatted": "",
                "date": "",
                "time": "",
                "weekday": "",
                "error": f"格式无效: {exc}",
            }
        return {
            "ok": True,
            "timestamp": round(now.timestamp(), 3),
            "timestamp_ms": int(now.timestamp() * 1000),
            "iso_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "local": now.strftime(DEFAULT_FORMAT),
            "formatted": formatted,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": WEEKDAY_CN[now.weekday()],
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "timestamp": 0,
            "timestamp_ms": 0,
            "iso_utc": "",
            "local": "",
            "formatted": "",
            "date": "",
            "time": "",
            "weekday": "",
            "error": str(exc),
        }
