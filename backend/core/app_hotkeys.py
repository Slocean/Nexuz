"""Always-on app hotkeys (start/continue run)."""

from __future__ import annotations

import threading
import time
from typing import Callable

from backend.core.hotkey_prefs import get_start_run_hotkey, get_start_run_label, to_pynput_hotkey


def _start_label() -> str:
    return get_start_run_label()


# Kept for older imports; prefer get_start_run_label().
START_LABEL = "X+F3"


class AppHotkeyWatcher:
    def __init__(self) -> None:
        self._listener = None
        self._lock = threading.Lock()
        self._last_fire = 0.0
        self._on_run: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(self, on_run: Callable[[], None] | None = None) -> None:
        self.stop()
        if on_run is not None:
            self._on_run = on_run
        if self._on_run is None:
            return

        def debounce() -> None:
            now = time.monotonic()
            with self._lock:
                if now - self._last_fire < 0.45:
                    return
                self._last_fire = now
            try:
                self._on_run()
            except Exception:
                pass

        try:
            from pynput import keyboard
        except Exception:
            return

        binding = to_pynput_hotkey(get_start_run_hotkey(), default=("x", "f3"))
        try:
            listener = keyboard.GlobalHotKeys({binding: debounce})
            listener.start()
            self._listener = listener
        except Exception:
            self._listener = None

    def restart(self) -> None:
        """Rebind after prefs change (keeps previous callback)."""
        if self._on_run is None:
            return
        self.start(on_run=self._on_run)

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
