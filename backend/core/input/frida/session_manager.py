"""Frida session manager for Unity UI click capture/playback."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from backend.core.input.frida.script_loader import load_unity_ui_click_script
from backend.core.input.types import (
    ERROR_FRIDA_NOT_ATTACHED,
    ERROR_FRIDA_SCRIPT,
    api_error,
    api_ok,
)


class FridaSessionManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session = None
        self._script = None
        self._device = None
        self._pid: int | None = None
        self._process_name: str | None = None
        self._attached = False
        self._hooked = False
        self._last_error: str | None = None
        self._on_detached: Callable[[], None] | None = None
        # run-local resolve cache: stable_id_key -> ptr string
        self._resolve_cache: dict[str, str] = {}

    def set_detached_callback(self, cb: Callable[[], None] | None) -> None:
        self._on_detached = cb

    def status(self) -> dict[str, Any]:
        with self._lock:
            script_status: dict[str, Any] = {}
            if self._script and self._attached:
                try:
                    script_status = self._call("status") or {}
                except Exception as exc:
                    script_status = {"error": str(exc)}
            return {
                "ok": True,
                "attached": bool(self._attached and self._script),
                "hooked": bool(script_status.get("hooked", self._hooked)),
                "recording": bool(script_status.get("recording")),
                "process_name": self._process_name,
                "pid": self._pid,
                "last_error": self._last_error or script_status.get("lastError"),
                "script": script_status,
            }

    def attach(self, process_name: str | None = None, pid: int | None = None) -> dict[str, Any]:
        try:
            import frida
        except ImportError:
            return api_error(ERROR_FRIDA_SCRIPT, "未安装 frida，请 pip install frida")

        with self._lock:
            if self._attached and self._script:
                return api_ok(**self.status())

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
                script.load()
                self._session = session
                self._script = script
                self._attached = True
                self._last_error = None
                self._resolve_cache.clear()

                # Install hooks
                hook_result = self._call("attachHooks")
                self._hooked = bool((hook_result or {}).get("ok", True))
                if isinstance(hook_result, dict) and not hook_result.get("ok", True):
                    self._last_error = str(hook_result.get("error") or hook_result.get("message") or "hook failed")
                    return api_error(ERROR_FRIDA_SCRIPT, self._last_error, **self.status())

                return api_ok(**self.status())
            except Exception as exc:
                self._cleanup_locked()
                self._last_error = str(exc)
                return api_error(ERROR_FRIDA_NOT_ATTACHED, f"Frida attach 失败: {exc}")

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
            return self._call(name, *args)

    def resolve_ptr(self, stable_id: dict[str, Any], *, use_cache: bool = True) -> str:
        from backend.core.input.frida.stable_id import stable_id_key, validate_stable_id

        ok, msg = validate_stable_id(stable_id)
        if not ok:
            raise RuntimeError(msg)
        key = stable_id_key(stable_id)
        with self._lock:
            if use_cache and key in self._resolve_cache:
                return self._resolve_cache[key]
            result = self._call("resolve", stable_id)
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
            self._resolve_cache[key] = ptr
            return ptr

    def _call(self, name: str, *args: Any) -> Any:
        script = self._script
        if not script:
            raise RuntimeError("Frida 脚本未加载")
        exports = getattr(script, "exports_sync", None) or getattr(script, "exports", None)
        if not exports:
            raise RuntimeError("Frida exports 不可用")
        fn = getattr(exports, name, None)
        if fn is None:
            # try lowercase (Frida often lowercases export names)
            fn = getattr(exports, name.lower(), None)
        if fn is None:
            raise RuntimeError(f"缺少 Frida export: {name}")
        raw = fn(*args) if args else fn()
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
        self._resolve_cache.clear()
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
