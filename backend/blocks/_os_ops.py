"""Shared OS-level helpers for system blocks (info, processes, power, volume).

All helpers degrade gracefully off-Windows: they return structured error dicts
instead of raising, so a flow that mixes platforms only fails the nodes that
really need Windows APIs.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"

# Known-folder GUIDs (SHGetKnownFolderPath). Keys map to sys_path options.
_KNOWN_FOLDERS = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "startup": "{B97D20BB-F46A-4C97-BA10-5E3608430854}",
    "recent": "{AE50C081-EBD2-438A-8655-8A092E34987A}",
    "appdata_roaming": "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}",
    "appdata_local": "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}",
    "program_files": "{905E63B6-C1BF-494E-B29C-65B732D3D21A}",
    "fonts": "{FD228CB7-AE11-4AE3-864C-16F3910AB8FE}",
}

# Processes that must never be terminated (BSOD / break the session).
_PROTECTED_NAMES = frozenset(
    {
        "system",
        "idle",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "memcompression",
    }
)


def _psutil():
    try:
        import psutil

        return psutil
    except Exception:
        return None


def is_process_protected(name: str, pid: int) -> bool:
    """True for PIDs / images that kill() must refuse (system critical)."""
    pid = int(pid or 0)
    if pid in (0, 4) or pid == os.getpid():
        return True
    return str(name or "").strip().lower() in _PROTECTED_NAMES


def memory_stats() -> dict[str, Any]:
    """Total / available / used-percent memory. psutil first, ctypes fallback."""
    psutil = _psutil()
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return {
                "total": int(vm.total),
                "available": int(vm.available),
                "used_percent": float(vm.percent),
            }
        except Exception:
            pass
    if IS_WINDOWS:

        class _MEM(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        try:
            stat = _MEM()
            stat.dwLength = ctypes.sizeof(_MEM)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = int(stat.ullTotalPhys)
                return {
                    "total": total,
                    "available": int(stat.ullAvailPhys),
                    "used_percent": round(100.0 * (total - int(stat.ullAvailPhys)) / max(total, 1), 1),
                }
        except Exception:
            pass
    return {"total": 0, "available": 0, "used_percent": 0.0}


def local_ip() -> str:
    """Primary outbound IPv4 (no traffic sent; UDP connect trick)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("223.5.5.5", 80))
            return str(s.getsockname()[0])
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


def known_folder(key: str) -> str:
    """Resolve a known folder by sys_path key; empty string when unavailable."""
    guid = _KNOWN_FOLDERS.get(str(key or "").strip())
    if guid and IS_WINDOWS:
        try:
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # GUID {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
            hexs = guid.strip("{}").split("-")
            g = _GUID()
            g.Data1 = int(hexs[0], 16)
            g.Data2 = int(hexs[1], 16)
            g.Data3 = int(hexs[2], 16)
            raw = bytes.fromhex(hexs[3] + hexs[4])
            for i, b in enumerate(raw):
                g.Data4[i] = b

            SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            SHGetKnownFolderPath.argtypes = [
                ctypes.POINTER(_GUID),
                ctypes.c_uint32,
                wintypes.HANDLE,
                ctypes.POINTER(ctypes.c_wchar_p),
            ]
            out = ctypes.c_wchar_p()
            if SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                return str(out.value or "")
        except Exception:
            pass
    # Non-Windows / API failure: coarse fallbacks for the common keys.
    home = Path.home()
    fallbacks = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "music": home / "Music",
        "pictures": home / "Pictures",
        "videos": home / "Videos",
        "appdata_roaming": Path(os.environ.get("APPDATA", "")),
        "appdata_local": Path(os.environ.get("LOCALAPPDATA", "")),
        "startup": Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup",
        "fonts": Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
        "program_files": Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
    }
    candidate = fallbacks.get(str(key or "").strip())
    return str(candidate) if candidate is not None else ""


def special_path(key: str) -> tuple[str, str]:
    """Return (path, error) for special-path keys, including the manual ones."""
    key = str(key or "").strip().lower()
    if key == "temp":
        return str(Path(os.environ.get("TEMP") or os.environ.get("TMP") or "")), ""
    if key == "windows":
        return str(Path(os.environ.get("WINDIR") or "C:\\Windows")), ""
    if key == "exe_dir":
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).parent), ""
        return str(Path(__file__).resolve().parent.parent.parent), ""
    path = known_folder(key)
    if path:
        return path, ""
    if key == "home":
        return str(Path.home()), ""
    return "", f"未知路径类型: {key}"


# --- power actions -----------------------------------------------------------


def lock_workstation() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "锁屏仅支持 Windows"
    try:
        if ctypes.windll.user32.LockWorkStation():
            return True, ""
        return False, f"LockWorkStation 失败（错误码 {ctypes.windll.kernel32.GetLastError()}）"
    except Exception as exc:
        return False, str(exc)


def monitor_off() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "息屏仅支持 Windows"
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SYSCOMMAND = 0x0112
        SC_MONITORPOWER = 0xF170
        result = ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2, 0x0002, 500,
            ctypes.byref(ctypes.c_long()),
        )
        if result:
            return True, ""
        return False, "息屏消息未确认"
    except Exception as exc:
        return False, str(exc)


def suspend_system(hibernate: bool) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "睡眠/休眠仅支持 Windows"
    try:
        ok = ctypes.windll.powrprof.SetSuspendState(
            1 if hibernate else 0, 0, 0
        )
        # SetSuspendState returns before the machine sleeps; nonzero = accepted.
        return (bool(ok), "" if ok else "SetSuspendState 被系统拒绝（未开休眠权限或组策略限制）")
    except Exception as exc:
        return False, str(exc)


def shutdown_command(mode: str, delay_sec: int, force: bool) -> tuple[bool, str]:
    """shutdown / restart / cancel via the built-in shutdown.exe."""
    if not IS_WINDOWS:
        return False, "关机/重启仅支持 Windows"
    args = ["shutdown"]
    if mode == "cancel":
        args.append("/a")
    else:
        flag = "/s" if mode == "shutdown" else "/r"
        delay = max(0, min(int(delay_sec or 0), 315360000))
        args += [flag, "/t", str(delay)]
        if force:
            args.append("/f")
        args += ["/d", "p:4:1"]
        args += ["/c", "Nexuz"]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0:
            return True, ""
        err = (completed.stderr or completed.stdout or "").strip() or f"退出码 {completed.returncode}"
        return False, err
    except Exception as exc:
        return False, str(exc)


# --- volume via media keys ---------------------------------------------------

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
_KEYEVENTF_KEYUP = 0x0002


def send_volume_key(vk: int, times: int = 1) -> tuple[bool, str]:
    """Tap a volume media key N times (keybd_event; works app-independent)."""
    if not IS_WINDOWS:
        return False, "音量控制仅支持 Windows"
    times = max(1, min(int(times or 1), 50))
    try:
        keybd = ctypes.windll.user32.keybd_event
        for _ in range(times):
            keybd(vk, 0, 0, 0)
            keybd(vk, 0, _KEYEVENTF_KEYUP, 0)
        return True, ""
    except Exception as exc:
        return False, str(exc)


# --- processes ---------------------------------------------------------------


def list_processes(name_filter: str = "", limit: int = 0) -> dict[str, Any]:
    """Enumerate running processes sorted by memory desc (psutil).

    Returns {"items": [...], "total": int, "filtered": int, "error": str}.
    """
    psutil = _psutil()
    if psutil is None:
        return {"items": [], "total": 0, "filtered": 0, "error": "psutil 未安装"}
    needle = str(name_filter or "").strip().lower()
    items: list[dict[str, Any]] = []
    total = 0
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        total += 1
        try:
            name = str(proc.info.get("name") or "")
            if needle and needle not in name.lower():
                continue
            mem = proc.info.get("memory_info")
            items.append(
                {
                    "pid": int(proc.info.get("pid") or 0),
                    "name": name,
                    "mem_mb": round(float(getattr(mem, "rss", 0) or 0) / (1024 * 1024), 1),
                }
            )
        except Exception:
            continue
    items.sort(key=lambda x: (-x["mem_mb"], x["pid"]))
    limit = max(0, int(limit or 0))
    return {
        "items": items[:limit] if limit > 0 else items,
        "total": total,
        "filtered": len(items),
        "error": "",
    }


def kill_processes(pid: int | None = None, name: str = "", force: bool = False) -> dict[str, Any]:
    """Terminate processes by pid or image name; protected targets are refused.

    Returns {"killed": [pid...], "refused": [{"pid","name","reason"}...],
             "not_found": int, "error": str}.
    """
    psutil = _psutil()
    if psutil is None:
        return {"killed": [], "refused": [], "not_found": 0, "error": "psutil 未安装"}

    targets: list[tuple[int, str]] = []
    not_found = 0
    if pid not in (None, 0, ""):
        try:
            proc = psutil.Process(int(pid))
            targets.append((int(proc.pid), proc.name() or ""))
        except psutil.NoSuchProcess:
            not_found = 1
    else:
        needle = str(name or "").strip().lower()
        if not needle:
            return {"killed": [], "refused": [], "not_found": 0, "error": "请填写进程 PID 或进程名"}
        # 精确匹配（允许省略 .exe）：notepad 命中 notepad.exe，但 system
        # 不得外溢到 SystemSettings.exe 之类的无关进程。
        for proc in psutil.process_iter(["pid", "name"]):
            pname = str(proc.info.get("name") or "")
            plain = pname.lower()
            stem = plain[:-4] if plain.endswith(".exe") else plain
            if plain == needle or stem == needle:
                targets.append((int(proc.info.get("pid") or 0), pname))

    killed: list[int] = []
    refused: list[dict[str, Any]] = []
    error = ""
    for tpid, tname in targets:
        if is_process_protected(tname, tpid):
            refused.append(
                {"pid": tpid, "name": tname, "reason": "系统关键进程，拒绝结束"}
            )
            continue
        try:
            proc = psutil.Process(tpid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                if force:
                    proc.kill()
                    proc.wait(timeout=3)
                else:
                    refused.append(
                        {"pid": tpid, "name": tname, "reason": "3 秒内未退出（可开启强制结束）"}
                    )
                    continue
            killed.append(tpid)
        except psutil.NoSuchProcess:
            not_found += 1
        except psutil.AccessDenied:
            refused.append({"pid": tpid, "name": tname, "reason": "权限不足（AccessDenied）"})
        except Exception as exc:
            refused.append({"pid": tpid, "name": tname, "reason": str(exc)})
    if not targets and not not_found:
        error = f"未找到进程: {name}"
    return {"killed": killed, "refused": refused, "not_found": not_found, "error": error}


# --- open path / url ---------------------------------------------------------


def open_target(target: str, show_in_explorer: bool = False) -> tuple[bool, str, str]:
    """Open a file/folder/URL with the OS default handler.

    Returns (ok, resolved, error). URLs open in the default browser; folders
    open in Explorer; show_in_explorer reveals a file selected in Explorer.
    """
    raw = str(target or "").strip().strip('"').strip("'")
    if not raw:
        return False, "", "路径/网址不能为空"
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://")):
        try:
            webbrowser.open(raw, new=1, autoraise=True)
            return True, raw, ""
        except Exception as exc:
            return False, raw, str(exc)
    if lowered.startswith(("file://",)):
        return False, raw, "仅支持本地路径或 http(s) 网址"
    path = Path(os.path.expandvars(raw)).expanduser()
    try:
        resolved = str(path.resolve(strict=False))
    except Exception:
        resolved = str(path)
    if not path.exists():
        return False, resolved, f"路径不存在: {resolved}"
    if show_in_explorer:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", resolved])
            return True, resolved, ""
        return False, resolved, "资源管理器定位仅支持 Windows"
    try:
        opener = (
            (lambda p: os.startfile(p))  # noqa: S606 - intended shell open
            if IS_WINDOWS
            else (lambda p: subprocess.Popen(["xdg-open", p]))
        )
        opener(resolved)
        return True, resolved, ""
    except Exception as exc:
        return False, resolved, str(exc)
