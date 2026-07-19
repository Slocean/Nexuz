"""Launch short-lived trusted-code workers with hard stop and resource limits."""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 60.0
DEFAULT_MEMORY_LIMIT_MB = 256
MAX_IPC_BYTES = 8 * 1024 * 1024
_ACTIVE_LOCK = threading.RLock()
_ACTIVE_WORKERS: dict[int, tuple[subprocess.Popen, "_WindowsJob | None"]] = {}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(value).hex()}
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    return repr(value)


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--trusted-worker"]
    return [sys.executable, "-m", "backend.core.trusted_worker"]


def _worker_root() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS))  # type: ignore[attr-defined]
    return str(Path(__file__).resolve().parents[2])


class _WindowsJob:
    def __init__(self, process_handle: int, memory_limit_mb: int):
        self.handle = None
        self._lock = threading.Lock()
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9

        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.BasicLimitInformation.ActiveProcessLimit = 1
        limit = max(64, int(memory_limit_mb)) * 1024 * 1024
        info.ProcessMemoryLimit = limit
        info.JobMemoryLimit = limit
        configured = kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            handle, wintypes.HANDLE(process_handle)
        )
        if not assigned:
            kernel32.CloseHandle(handle)
            return
        self.handle = handle
        self._kernel32 = kernel32

    def close(self) -> None:
        with self._lock:
            if self.handle:
                self._kernel32.CloseHandle(self.handle)
                self.handle = None


def _terminate_tree(process: subprocess.Popen, job: _WindowsJob | None) -> None:
    if job and job.handle:
        job.close()
    elif os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=0x08000000,
                check=False,
            )
        except Exception:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            process.kill()
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def terminate_all_workers() -> int:
    """Hard-stop every active trusted-code worker, including process trees."""
    with _ACTIVE_LOCK:
        active = list(_ACTIVE_WORKERS.values())
        _ACTIVE_WORKERS.clear()
    for process, job in active:
        if process.poll() is None:
            _terminate_tree(process, job)
        elif job:
            job.close()
    return len(active)


atexit.register(terminate_all_workers)


def run_isolated(
    request: dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    timeout = min(MAX_TIMEOUT_SECONDS, max(0.1, float(timeout_seconds)))
    payload = json.dumps(request, ensure_ascii=False, default=_json_default).encode("utf-8")
    if len(payload) > MAX_IPC_BYTES:
        return {
            "ok": False,
            "error": f"可信代码输入超过 IPC 上限（{MAX_IPC_BYTES // (1024 * 1024)} MB）",
        }
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = 0x08000000 | 0x00000200
    else:
        popen_kwargs["start_new_session"] = True

    with tempfile.TemporaryDirectory(prefix="nexuz-worker-") as work_dir:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "HOMEDRIVE": os.environ.get("HOMEDRIVE", ""),
            "HOMEPATH": os.environ.get("HOMEPATH", ""),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
            "APPDATA": os.environ.get("APPDATA", ""),
            "TEMP": work_dir,
            "TMP": work_dir,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONPATH": _worker_root(),
        }
        process = subprocess.Popen(
            _worker_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=work_dir,
            env=env,
            creationflags=creationflags,
            **popen_kwargs,
        )
        job = (
            _WindowsJob(int(process._handle), memory_limit_mb)  # type: ignore[attr-defined]
            if os.name == "nt"
            else None
        )
        with _ACTIVE_LOCK:
            _ACTIVE_WORKERS[process.pid] = (process, job)
        try:
            io_result: dict[str, bytes] = {}

            def communicate() -> None:
                try:
                    stdout_bytes, stderr_bytes = process.communicate(input=payload)
                    io_result["stdout"] = stdout_bytes or b""
                    io_result["stderr"] = stderr_bytes or b""
                except Exception as exc:
                    io_result["error"] = str(exc).encode("utf-8", errors="replace")

            io_thread = threading.Thread(target=communicate, daemon=True)
            io_thread.start()
            started = time.monotonic()
            while io_thread.is_alive():
                if should_stop is not None and should_stop():
                    _terminate_tree(process, job)
                    io_thread.join(timeout=2)
                    raise InterruptedError("流程已停止，脚本 worker 已终止")
                if time.monotonic() - started >= timeout:
                    _terminate_tree(process, job)
                    io_thread.join(timeout=2)
                    return {
                        "ok": False,
                        "error": f"可信代码执行超时（{timeout:g} 秒），worker 已终止",
                    }
                time.sleep(0.05)

            if should_stop is not None and should_stop():
                raise InterruptedError("流程已停止，脚本 worker 已终止")
            stdout_bytes = io_result.get("stdout", b"")
            stderr_bytes = io_result.get("stderr", b"")
            if io_result.get("error") and not stdout_bytes:
                return {
                    "ok": False,
                    "error": "可信代码 worker 通信失败",
                    "detail": io_result["error"].decode("utf-8", errors="replace"),
                }
            if len(stdout_bytes) > MAX_IPC_BYTES:
                return {
                    "ok": False,
                    "error": f"可信代码输出超过 IPC 上限（{MAX_IPC_BYTES // (1024 * 1024)} MB）",
                }
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            try:
                response = json.loads(stdout)
            except Exception:
                return {
                    "ok": False,
                    "error": "无法解析可信代码 worker 返回",
                    "detail": (stderr or stdout)[-2000:],
                }
            if not isinstance(response, dict):
                return {"ok": False, "error": "可信代码 worker 返回格式无效"}
            return response
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_WORKERS.pop(process.pid, None)
            if process.poll() is None:
                _terminate_tree(process, job)
            elif job:
                job.close()
