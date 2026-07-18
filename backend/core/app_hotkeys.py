"""Always-on app hotkeys (start/continue run + toggle plugin mode)."""

from __future__ import annotations

import threading
import time
from typing import Callable

from backend.core.hotkey_prefs import (
    get_plugin_mode_hotkey,
    get_start_run_hotkey,
    get_start_run_label,
    to_pynput_hotkey,
)


def _start_label() -> str:
    return get_start_run_label()


# Kept for older imports; prefer get_start_run_label().
START_LABEL = "X+F3"


class AppHotkeyWatcher:
    def __init__(self) -> None:
        self._listener = None
        self._lock = threading.Lock()
        self._last_fire_run = 0.0
        self._last_fire_plugin = 0.0
        self._on_run: Callable[[], None] | None = None
        self._on_plugin_mode: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(
        self,
        on_run: Callable[[], None] | None = None,
        on_plugin_mode: Callable[[], None] | None = None,
    ) -> None:
        self.stop()
        if on_run is not None:
            self._on_run = on_run
        if on_plugin_mode is not None:
            self._on_plugin_mode = on_plugin_mode
        if self._on_run is None and self._on_plugin_mode is None:
            return

        def debounce_run() -> None:
            if self._on_run is None:
                return
            now = time.monotonic()
            with self._lock:
                if now - self._last_fire_run < 0.45:
                    return
                self._last_fire_run = now
            try:
                self._on_run()
            except Exception:
                pass

        def debounce_plugin() -> None:
            if self._on_plugin_mode is None:
                return
            now = time.monotonic()
            with self._lock:
                if now - self._last_fire_plugin < 0.45:
                    return
                self._last_fire_plugin = now
            try:
                self._on_plugin_mode()
            except Exception:
                pass

        try:
            from pynput import keyboard
        except Exception:
            return

        mapping: dict[str, Callable[[], None]] = {}
        if self._on_run is not None:
            mapping[to_pynput_hotkey(get_start_run_hotkey(), default=("x", "f3"))] = debounce_run
        if self._on_plugin_mode is not None:
            mapping[
                to_pynput_hotkey(get_plugin_mode_hotkey(), default=("x", "f6"))
            ] = debounce_plugin
        if not mapping:
            return
        try:
            listener = keyboard.GlobalHotKeys(mapping)
            listener.start()
            self._listener = listener
        except Exception:
            self._listener = None

    def restart(self) -> None:
        """Rebind after prefs change (keeps previous callbacks)."""
        if self._on_run is None and self._on_plugin_mode is None:
            return
        self.start(on_run=self._on_run, on_plugin_mode=self._on_plugin_mode)

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass


_watcher: AppHotkeyWatcher | None = None


def get_app_hotkeys() -> AppHotkeyWatcher:
    global _watcher
    if _watcher is None:
        _watcher = AppHotkeyWatcher()
    return _watcher
