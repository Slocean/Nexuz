"""Recording session: routes to CaptureProvider, window hide, overlays."""

from __future__ import annotations

import threading
from typing import Any, Callable

from backend.core.input.provider_registry import get_provider_registry
from backend.core.input.resolve import coerce_mode
from backend.core.input.types import (
    ERROR_NOT_RECORDING,
    ERROR_RECORDING_ACTIVE,
    api_error,
    api_ok,
)


class RecordingSession:
    def __init__(
        self,
        *,
        set_window_visible: Callable[[bool], None] | None = None,
        emit: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._mode: str = "coord"
        self._hidden = False
        self._set_window_visible = set_window_visible
        self._emit = emit
        self._on_stop_hotkey: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def hidden(self) -> bool:
        return self._hidden

    def set_stop_hotkey_callback(self, cb: Callable[[], None] | None) -> None:
        self._on_stop_hotkey = cb
        # Keep coord recorder hotkey in sync
        from backend.core.recorder import get_recorder

        get_recorder().set_stop_hotkey_callback(cb)

    def start(
        self,
        mode: str = "coord",
        *,
        min_interval_ms: int = 50,
        hide_window: bool = False,
    ) -> dict[str, Any]:
        mode = coerce_mode(mode)
        with self._lock:
            if self._active:
                return api_error(ERROR_RECORDING_ACTIVE, "已在录制中")
            registry = get_provider_registry()
            provider_or_err = registry.require_capture(mode)
            if isinstance(provider_or_err, dict):
                return provider_or_err
            provider = provider_or_err

            from backend.core.record_overlay import hide_stop_overlay, show_stop_overlay

            self._hidden = bool(hide_window)
            if self._hidden and self._set_window_visible:
                self._set_window_visible(False)
                show_stop_overlay(lambda: self._fire_stop_hotkey())
            else:
                hide_stop_overlay()

            try:
                provider.start_sequence(min_interval_ms=int(min_interval_ms))
            except Exception as exc:
                if self._hidden and self._set_window_visible:
                    self._set_window_visible(True)
                hide_stop_overlay()
                self._hidden = False
                return api_error("RECORD_START_FAILED", str(exc))

            self._active = True
            self._mode = mode
            return api_ok(
                mode=mode,
                hide_window=self._hidden,
                stop_hotkey="Ctrl+Shift+F10",
            )

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                return api_error(ERROR_NOT_RECORDING, "当前未在录制")
            mode = self._mode
            registry = get_provider_registry()
            provider = registry.get_capture(mode)
            nodes: list[dict[str, Any]] = []
            if provider:
                try:
                    nodes = provider.stop_sequence()
                except Exception as exc:
                    nodes = []
                    err = str(exc)
                else:
                    err = None
            else:
                err = f"录入模式不可用: {mode}"

            from backend.core.record_overlay import hide_stop_overlay

            hide_stop_overlay()
            if self._hidden and self._set_window_visible:
                self._set_window_visible(True)
            self._hidden = False
            self._active = False

            if err:
                return api_error("RECORD_STOP_FAILED", err, nodes=nodes, mode=mode)
            return api_ok(nodes=nodes, mode=mode)

    def pick_click(self, mode: str = "coord", *, hide_window: bool = True, timeout_s: float = 120) -> dict[str, Any]:
        mode = coerce_mode(mode)
        registry = get_provider_registry()
        provider_or_err = registry.require_capture(mode)
        if isinstance(provider_or_err, dict):
            return provider_or_err
        provider = provider_or_err

        do_hide = bool(hide_window) and self._set_window_visible is not None
        if do_hide:
            self._set_window_visible(False)
        try:
            return provider.pick_single(timeout_s=timeout_s)
        finally:
            if do_hide:
                self._set_window_visible(True)

    def _fire_stop_hotkey(self) -> None:
        cb = self._on_stop_hotkey
        if cb:
            threading.Thread(target=cb, daemon=True).start()


_session: RecordingSession | None = None


def get_recording_session(
    *,
    set_window_visible: Callable[[bool], None] | None = None,
    emit: Callable[[str, dict], None] | None = None,
) -> RecordingSession:
    global _session
    if _session is None:
        _session = RecordingSession(set_window_visible=set_window_visible, emit=emit)
    else:
        if set_window_visible is not None:
            _session._set_window_visible = set_window_visible
        if emit is not None:
            _session._emit = emit
    return _session
