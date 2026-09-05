"""Single-request worker for trusted scripts and user plugins.

The process boundary protects the desktop process from crashes and hangs. It is
not an OS security boundary: code still runs as the current Windows user.
Trusted user plugins (kind=plugin + allow_write) may write files — image
processing plugins persist their output to disk. For such requests the worker
stays at the caller's integrity level (Low integrity would forbid writing
user-writable paths); network and child processes stay blocked for every kind.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _apply_windows_low_integrity() -> None:
    """Lower this worker to Windows Low integrity before executing user code."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    TOKEN_ADJUST_DEFAULT = 0x0080
    TOKEN_QUERY = 0x0008
    TokenIntegrityLevel = 25
    SE_GROUP_INTEGRITY = 0x00000020

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.SetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    advapi32.SetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    sid = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_DEFAULT | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    try:
        if not advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
            raise OSError(ctypes.get_last_error(), "ConvertStringSidToSidW failed")
        label = TOKEN_MANDATORY_LABEL(
            SID_AND_ATTRIBUTES(sid, SE_GROUP_INTEGRITY)
        )
        size = ctypes.sizeof(label) + advapi32.GetLengthSid(sid)
        if not advapi32.SetTokenInformation(
            token,
            TokenIntegrityLevel,
            ctypes.byref(label),
            size,
        ):
            raise OSError(ctypes.get_last_error(), "SetTokenInformation failed")
    finally:
        if sid:
            kernel32.LocalFree(sid)
        kernel32.CloseHandle(token)


def _install_audit_policy(*, allow_write: bool = False) -> None:
    """Block common network and child-process APIs inside the worker.

    File writes are blocked unless allow_write（本机可信用户插件落盘产出）。
    """

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event.startswith("socket."):
            raise PermissionError("可信代码 worker 默认禁止网络访问")
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.spawn",
            "pty.spawn",
        }:
            raise PermissionError("可信代码 worker 禁止启动子进程")
        if not allow_write and event == "open" and len(args) >= 2:
            mode = str(args[1] or "")
            flags = args[2] if len(args) > 2 else 0
            write_flags = 0
            for name in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"):
                write_flags |= int(getattr(os, name, 0))
            if any(mark in mode for mark in ("w", "a", "x", "+")) or (
                isinstance(flags, int) and flags & write_flags
            ):
                raise PermissionError("可信代码 worker 默认禁止文件写入")

    sys.addaudithook(audit)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(value).hex()}
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return repr(value)


def _run_script(request: dict[str, Any]) -> dict[str, Any]:
    from backend.blocks._script_sandbox import run_user_script

    return run_user_script(
        str(request.get("code") or ""),
        context=request.get("context") if isinstance(request.get("context"), dict) else {},
        inputs=request.get("inputs") if isinstance(request.get("inputs"), dict) else {},
    )


def _run_plugin(request: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(request.get("path") or "")).resolve()
    expected_type = str(request.get("block_type") or "")
    if not path.is_file() or path.suffix.lower() != ".py":
        raise ValueError("用户积木文件无效")

    module_name = f"nexuz_isolated_plugin_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载用户积木: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = getattr(module, "SCHEMA", None)
    handler = getattr(module, "handler", None)
    if not isinstance(schema, dict) or str(schema.get("type") or "") != expected_type:
        raise ValueError("用户积木 SCHEMA.type 与注册信息不一致")
    if not callable(handler):
        raise ValueError("用户积木缺少 handler")

    kwargs = request.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
    result = handler(
        request.get("params") if isinstance(request.get("params"), dict) else {},
        request.get("context") if isinstance(request.get("context"), dict) else {},
        **kwargs,
    )
    return result if isinstance(result, dict) else {"result": result}


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    kind = str(request.get("kind") or "")
    if kind == "script":
        return _run_script(request)
    if kind == "plugin":
        return _run_plugin(request)
    raise ValueError(f"未知 worker 请求: {kind}")


def main() -> int:
    # 载荷恒为 UTF-8 JSON：worker_client 会设 PYTHONIOENCODING/PYTHONUTF8，
    # 但其他启动方式（CI、手动 -m）可能落在 ANSI 代码页上，中文错误信息
    # 会编码失败导致 stdout 全空——这里强制原始 stdout 为 UTF-8。
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    original_stdout = sys.stdout
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        raw = sys.stdin.buffer.read()
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("worker 请求必须是对象")
        # 仅本机可信用户积木（kind=plugin 且显式 allow_write）放行文件写入；
        # 脚本积木与网络/子进程限制不因此放松。Low 完整级会连带禁止写
        # 用户可写目录（Medium IL 文件的 No-Write-Up），放行写入时须跳过。
        allow_write = bool(request.get("allow_write")) and request.get("kind") == "plugin"
        if not allow_write:
            _apply_windows_low_integrity()
        _install_audit_policy(allow_write=allow_write)
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
            captured_stderr
        ):
            result = handle_request(request)
        payload = {
            "ok": True,
            "result": result,
            "worker_stdout": captured_stdout.getvalue(),
            "worker_stderr": captured_stderr.getvalue(),
        }
    except BaseException as exc:
        payload = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=20),
            "worker_stdout": captured_stdout.getvalue(),
            "worker_stderr": captured_stderr.getvalue(),
        }
    original_stdout.write(json.dumps(payload, ensure_ascii=False, default=_json_default))
    original_stdout.flush()
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
