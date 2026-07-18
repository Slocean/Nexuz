"""Global hotkeys while a flow is running (works even if main window is hidden)."""

from __future__ import annotations

import threading
import time
from typing import Callable

from backend.core.hotkey_prefs import (
    get_pause_run_hotkey,
    get_pause_run_label,
    get_stop_run_hotkey,
    get_stop_run_label,
    to_pynput_hotkey,
)


def _stop_label() -> str:
    return get_stop_run_label()


def _pause_label() -> str:
    return get_pause_run_label()


# Kept for older imports; prefer get_*_run_label().
STOP_LABEL = "X+F4"
PAUSE_LABEL = "X+F5"


class RunHotkeyWatcher:
    def __init__(self) -> None:
        self._listener = None
        self._lock = threading.Lock()
        self._last_fire = 0.0
        self._on_stop: Callable[[], None] | None = None
        self._on_pause: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(
        self,
        on_stop: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
    ) -> None:
        self.stop()
        if on_stop is not None:
            self._on_stop = on_stop
        if on_pause is not None:
            self._on_pause = on_pause

        def debounce(fn: Callable[[], None] | None) -> Callable[[], None]:
            def wrapped() -> None:
                if fn is None:
                    return
                now = time.monotonic()
                with self._lock:
                    if now - self._last_fire < 0.4:
                        return
                    self._last_fire = now
                try:
                    fn()
                except Exception:
                    pass

            return wrapped

        try:
            from pynput import keyboard
        except Exception:
            return

        stop_bind = to_pynput_hotkey(get_stop_run_hotkey(), default=("x", "f4"))
        pause_bind = to_pynput_hotkey(get_pause_run_hotkey(), default=("x", "f5"))
        mapping: dict = {}
        if self._on_stop is not None:
            mapping[stop_bind] = debounce(self._on_stop)
        if self._on_pause is not None:
            # If same binding (shouldn't happen after prefs validation), last wins.
            mapping[pause_bind] = debounce(self._on_pause)
        if not mapping:
            return
        try:
            listener = keyboard.GlobalHotKeys(mapping)
            listener.start()
            self._listener = listener
        except Exception:
            self._listener = None

    def restart(self) -> None:
        """Rebind while a run is active."""
        if not self.active:
            return
        self.start(on_stop=self._on_stop, on_pause=self._on_pause)

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass


_watcher: RunHotkeyWatcher | None = None


def get_run_hotkeys() -> RunHotkeyWatcher:
    global _watcher
    if _watcher is None:
        _watcher = RunHotkeyWatcher()
    return _watcher
