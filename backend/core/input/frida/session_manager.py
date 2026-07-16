"""Frida session manager for Unity UI click capture/playback."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable

from backend.core.input.frida.script_loader import load_unity_ui_click_script
from backend.core.input.types import (
    ERROR_FRIDA_NOT_ATTACHED,
    ERROR_FRIDA_SCRIPT,
    api_error,
    api_ok,
)

_log = logging.getLogger(__name__)

# Hard timeouts for exports_sync (seconds)
_CALL_TIMEOUTS: dict[str, float] = {
    "attachhooks": 12.0,
    "status": 2.0,
    "invokeclick": 6.0,
    "resolve": 6.0,
    "startsequencerecord": 5.0,
    "stopsequencerecord": 5.0,
    "setrecordtarget": 5.0,
    "drainrecorded": 3.0,
}
_CALL_TIMEOUT_DEFAULT = 8.0

# Idle auto-detach (seconds)
_IDLE_DETACH_S = 10 * 60
# How often status() may probe the script over RPC when probe=False
_STATUS_PROBE_INTERVAL_S = 30.0


class FridaSessionManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Serializes Frida exports_sync; separate from _lock so status fast-path is not blocked
        self._rpc_lock = threading.Lock()
        self._session = None
        self._script = None
        self._device = None
        self._pid: int | None = None
        self._process_name: str | None = None
        self._attached = False
        self._hooked = False
        self._recording = False
        self._last_error: str | None = None
        self._on_detached: Callable[[], None] | None = None
        # run-local resolve cache: stable_id_key -> ptr string
        self._resolve_cache: dict[str, str] = {}
        self._last_used_at = 0.0
        self._last_script_probe_at = 0.0
        self._call_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frida-rpc")

    def set_detached_callback(self, cb: Callable[[], None] | None) -> None:
        self._on_detached = cb

    def _touch(self) -> None:
        self._last_used_at = time.monotonic()

    def _maybe_idle_detach_locked(self) -> bool:
        """Detach if idle too long and not recording. Caller holds lock. Returns True if detached."""
        if not self._attached:
            return False
        if self._recording:
            return False
        if not self._last_used_at:
            return False
        idle = time.monotonic() - self._last_used_at
        if idle < _IDLE_DETACH_S:
            return False
        _log.info(
            "Frida idle %.0fs (>= %ss) — auto detach from %s",
            idle,
            _IDLE_DETACH_S,
            self._process_name or self._pid,
        )
        self._last_error = f"空闲超过 {_IDLE_DETACH_S // 60} 分钟，已自动断开"
        self._cleanup_locked()
        return True

    def status(self, *, probe: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._maybe_idle_detach_locked():
                return {
                    "ok": True,
                    "attached": False,
                    "hooked": False,
                    "recording": False,
                    "process_name": None,
                    "pid": None,
                    "last_error": self._last_error,
                    "script": {},
                    "auto_detached": True,
                }

            script_status: dict[str, Any] = {}
            should_probe = bool(probe)
            if (
                not should_probe
                and self._script
                and self._attached
                and self._last_script_probe_at
                and (time.monotonic() - self._last_script_probe_at) >= _STATUS_PROBE_INTERVAL_S
            ):
                should_probe = True

            script = self._script if (should_probe and self._attached) else None

        if script is not None:
            try:
                script_status = self._invoke_export(script, "status") or {}
                with self._lock:
                    self._last_script_probe_at = time.monotonic()
                    if isinstance(script_status, dict):
                        if "hooked" in script_status:
                            self._hooked = bool(script_status.get("hooked"))
                        if "recording" in script_status:
                            self._recording = bool(script_status.get("recording"))
                        err = script_status.get("lastError")
                        if err:
                            self._last_error = str(err)
            except Exception as exc:
                script_status = {"error": str(exc)}

        with self._lock:
            return {
                "ok": True,
                "attached": bool(self._attached and self._script),
                "hooked": bool(self._hooked),
                "recording": bool(self._recording),
                "process_name": self._process_name,
                "pid": self._pid,
                "last_error": self._last_error
                or (script_status.get("lastError") if isinstance(script_status, dict) else None),
                "script": script_status,
            }

    def list_processes(
        self,
        query: str | None = None,
        only_with_window: bool = True,
    ) -> dict[str, Any]:
        """Enumerate processes; default only those with a visible window (dedupe helpers)."""
        from backend.core.input.frida.process_list import enrich_process_rows

        rows: list[dict[str, Any]] = []
        try:
            import frida

            device = frida.get_local_device()
            for proc in device.enumerate_processes():
                name = str(getattr(proc, "name", "") or "")
                pid = int(getattr(proc, "pid", 0) or 0)
                if not pid or not name:
                    continue
                rows.append({"pid": pid, "name": name})
        except ImportError:
            return api_error(ERROR_FRIDA_SCRIPT, "未安装 frida，请 pip install frida")
        except Exception as exc:
            try:
                import psutil

                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        info = proc.info
                        name = str(info.get("name") or "")
                        pid = int(info.get("pid") or 0)
                        if not pid or not name:
                            continue
                        rows.append({"pid": pid, "name": name})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                return api_error(ERROR_FRIDA_SCRIPT, f"枚举进程失败: {exc}")

        enriched = enrich_process_rows(
            rows,
            query=query,
            only_with_window=bool(only_with_window),
        )
        return api_ok(
            processes=enriched,
            count=len(enriched),
            only_with_window=bool(only_with_window),
        )

    def attach(self, process_name: str | None = None, pid: int | None = None) -> dict[str, Any]:
        try:
            import frida
        except ImportError:
            return api_error(ERROR_FRIDA_SCRIPT, "未安装 frida，请 pip install frida")

        with self._lock:
            if self._attached and self._script:
                self._touch()
                return api_ok(
                    attached=True,
                    hooked=bool(self._hooked),
                    recording=bool(self._recording),
                    process_name=self._process_name,
                    pid=self._pid,
                    last_error=self._last_error,
                )

            session = None
            script = None
            try:
                device = frida.get_local_device()
                self._device = device
                if pid:
                    session = device.attach(int(pid))
                    self._pid = int(pid)
                    self._process_name = process_name or str(pid)
                else:
                    name = (process_name or "").strip()
                    if not name:
                        return api_error(ERROR_FRIDA_NOT_ATTACHED, "请指定进程名或 PID")
                    session = device.attach(name)
                    self._process_name = name
                    try:
                        self._pid = int(session._impl.pid)  # type: ignore[attr-defined]
                    except Exception:
                        self._pid = None

                def on_detached(reason, *args):
                    self._handle_detached(str(reason))

                try:
                    session.on("detached", on_detached)
                except Exception:
                    pass

                source = load_unity_ui_click_script()
                script = session.create_script(source)

                def on_message(message, _data):
                    if isinstance(message, dict) and message.get("type") == "error":
                        self._last_error = str(
                            message.get("description")
                            or message.get("stack")
                            or message
                        )

                try:
                    script.on("message", on_message)
                except Exception:
                    pass

                script.load()
                self._session = session
                self._script = script
                self._attached = True
                self._recording = False
                self._resolve_cache.clear()
                self._touch()
                script_ref = script

            except Exception as exc:
                self._script = script
                self._session = session
                self._cleanup_locked()
                self._last_error = str(exc)
                return api_error(ERROR_FRIDA_NOT_ATTACHED, f"Frida attach 失败: {exc}")

        # Soft-fail hooks outside state lock so UI status polls are not blocked
        hook_warning = None
        try:
            hook_result = self._invoke_export(script_ref, "attachHooks")
        except Exception as hook_exc:
            hook_result = {"ok": False, "error": str(hook_exc)}

        with self._lock:
            if not self._attached or self._script is not script_ref:
                return api_error(ERROR_FRIDA_NOT_ATTACHED, "Frida 在 Hook 过程中已断开")
            if isinstance(hook_result, dict) and not hook_result.get("ok", True):
                self._hooked = False
                hook_warning = str(
                    hook_result.get("error")
                    or hook_result.get("message")
                    or "UI Hook 未就绪"
                )
                self._last_error = hook_warning
            else:
                self._hooked = True
                self._last_error = None
                if isinstance(hook_result, dict) and hook_result.get("warning"):
                    hook_warning = str(hook_result.get("warning"))
                    self._last_error = hook_warning
                if isinstance(hook_result, dict) and hook_result.get("replay") is False:
                    if not hook_warning:
                        hook_warning = "录制可用，但主线程回放未就绪"
                        self._last_error = hook_warning

            st = {
                "attached": True,
                "hooked": bool(self._hooked),
                "recording": bool(self._recording),
                "process_name": self._process_name,
                "pid": self._pid,
                "last_error": self._last_error,
                "script": {},
            }
            if isinstance(hook_result, dict):
                if "replay" in hook_result:
                    st["replay"] = bool(hook_result.get("replay"))
                if "mainThread" in hook_result:
                    st["main_thread"] = bool(hook_result.get("mainThread"))
            if hook_warning:
                st["warning"] = hook_warning
            return api_ok(**st)

    def detach(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_locked()
            return api_ok(attached=False)

    def clear_resolve_cache(self) -> None:
        with self._lock:
            self._resolve_cache.clear()

    def call_export(self, name: str, *args: Any) -> Any:
        with self._lock:
            if not self._attached or not self._script:
                raise RuntimeError("Frida 未连接")
            self._touch()
            script = self._script

        result = self._invoke_export(script, name, *args)

        with self._lock:
            lname = name.lower().replace("_", "")
            if lname == "startsequencerecord":
                self._recording = True
            elif lname == "stopsequencerecord":
                self._recording = False
            elif lname == "setrecordtarget":
                self._recording = bool(args[0]) if args else False
        return result

    def resolve_ptr(self, stable_id: dict[str, Any], *, use_cache: bool = True) -> str:
        from backend.core.input.frida.stable_id import stable_id_key, validate_stable_id

        ok, msg = validate_stable_id(stable_id)
        if not ok:
            raise RuntimeError(msg)
        key = stable_id_key(stable_id)
        with self._lock:
            if use_cache and key in self._resolve_cache:
                self._touch()
                return self._resolve_cache[key]
            if not self._attached or not self._script:
                raise RuntimeError("Frida 未连接")
            self._touch()
            script = self._script

        result = self._invoke_export(script, "resolve", stable_id)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        if not isinstance(result, dict) or not result.get("ok"):
            err = (result or {}).get("error") if isinstance(result, dict) else "resolve failed"
            raise RuntimeError(str(err))
        ptr = str(result.get("ptr") or "")
        if not ptr:
            raise RuntimeError("resolve 返回空指针")
        with self._lock:
            self._resolve_cache[key] = ptr
        return ptr

    def _call_timeout(self, name: str) -> float:
        key = name.lower().replace("_", "")
        return _CALL_TIMEOUTS.get(key, _CALL_TIMEOUT_DEFAULT)

    def _invoke_export(self, script: Any, name: str, *args: Any) -> Any:
        """Run a Frida export with hard timeout. Does not hold _lock."""
        exports = getattr(script, "exports_sync", None) or getattr(script, "exports", None)
        if not exports:
            raise RuntimeError("Frida exports 不可用")
        fn = getattr(exports, name, None)
        if fn is None:
            fn = getattr(exports, name.lower(), None)
        if fn is None:
            raise RuntimeError(f"缺少 Frida export: {name}")

        timeout = self._call_timeout(name)

        def _invoke() -> Any:
            return fn(*args) if args else fn()

        with self._rpc_lock:
            try:
                fut = self._call_pool.submit(_invoke)
                raw = fut.result(timeout=timeout)
            except FuturesTimeout:
                msg = f"Frida RPC 超时 ({name}, {timeout:.0f}s)"
                with self._lock:
                    self._last_error = msg
                raise RuntimeError(msg)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                raise

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return raw
        return raw

    def _handle_detached(self, reason: str) -> None:
        with self._lock:
            self._last_error = f"detached: {reason}"
            self._cleanup_locked()
        cb = self._on_detached
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _cleanup_locked(self) -> None:
        script = self._script
        session = self._session
        self._script = None
        self._session = None
        self._attached = False
        self._hooked = False
        self._recording = False
        self._resolve_cache.clear()
        self._last_used_at = 0.0
        self._last_script_probe_at = 0.0
        if script:
            try:
                script.unload()
            except Exception:
                pass
        if session:
            try:
                session.detach()
            except Exception:
                pass


_manager: FridaSessionManager | None = None


def get_frida_session_manager() -> FridaSessionManager:
    global _manager
    if _manager is None:
        _manager = FridaSessionManager()
    return _manager


def reset_frida_session_manager_for_tests() -> None:
    global _manager
    if _manager is not None:
        try:
            _manager.detach()
        except Exception:
            pass
    _manager = None
