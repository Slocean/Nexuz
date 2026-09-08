"""系统信息：一次性读取操作系统 / 主机 / 内存 / 网络等基本信息，供流程分支或日志使用。"""

from __future__ import annotations

import os
import platform
import socket
import sys
from typing import Any

from backend.blocks._os_ops import IS_WINDOWS, local_ip, memory_stats

SCHEMA = {
    "type": "system_info",
    "description": "返回系统信息（主机名/系统版本/CPU/内存）。",
    "label": "系统信息",
    "category": "系统类",
    "done_log": "系统：{{os_name}} {{os_version}}，用户：{{username}}",
    "inputs": [],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "os_name", "type": "string"},
        {"name": "os_version", "type": "string"},
        {"name": "arch", "type": "string"},
        {"name": "hostname", "type": "string"},
        {"name": "username", "type": "string"},
        {"name": "cpu_count", "type": "number"},
        {"name": "mem_total_gb", "type": "number"},
        {"name": "mem_free_gb", "type": "number"},
        {"name": "mem_used_percent", "type": "number"},
        {"name": "local_ip", "type": "string"},
        {"name": "python_version", "type": "string"},
        {"name": "is_admin", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def _is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes_is_admin())
    except Exception:
        return False


def ctypes_is_admin() -> bool:
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def handler(params, context, **kwargs):
    mem = memory_stats()
    try:
        os_name = platform.system() or sys.platform
        if IS_WINDOWS:
            release, _ver, _csd, _ptype = platform.win32_ver()
            build = platform.version().split(".")[-1] if platform.version() else ""
            os_version = f"{release} (build {build})".strip()
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                )
                display = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
                product = str(winreg.QueryValueEx(key, "ProductName")[0])
                winreg.CloseKey(key)
                os_name = product or "Windows"
                os_version = f"{release} {display} (build {build})".strip()
            except Exception:
                pass
        else:
            os_version = platform.release()
        return {
            "ok": True,
            "os_name": os_name,
            "os_version": os_version,
            "arch": platform.machine() or "",
            "hostname": socket.gethostname(),
            "username": os.environ.get("USERNAME") or os.environ.get("USER") or "",
            "cpu_count": os.cpu_count() or 0,
            "mem_total_gb": round(mem["total"] / (1024 ** 3), 2),
            "mem_free_gb": round(mem["available"] / (1024 ** 3), 2),
            "mem_used_percent": round(float(mem["used_percent"]), 1),
            "local_ip": local_ip(),
            "python_version": platform.python_version(),
            "is_admin": _is_admin(),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "os_name": "",
            "os_version": "",
            "arch": "",
            "hostname": "",
            "username": "",
            "cpu_count": 0,
            "mem_total_gb": 0,
            "mem_free_gb": 0,
            "mem_used_percent": 0,
            "local_ip": "",
            "python_version": "",
            "is_admin": False,
            "error": str(exc),
        }
