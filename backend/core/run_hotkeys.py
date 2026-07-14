"""Global hotkeys while a flow is running (works even if main window is hidden)."""

from __future__ import annotations

import threading
import time
from typing import Callable


# Ctrl+X+F4 → stop, Ctrl+X+F5 → pause (same Ctrl+X prefix as recording stop Ctrl+X+F10).
STOP_HOTKEY = "<ctrl>+x+<f4>"
PAUSE_HOTKEY = "<ctrl>+x+<f5>"
STOP_LABEL = "Ctrl+X+F4"
PAUSE_LABEL = "Ctrl+X+F5"


class RunHotkeyWatcher:
    def __init__(self) -> None:
        self._listener = None
        self._lock = threading.Lock()
        self._last_fire = 0.0

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(
        self,
        on_stop: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
    ) -> None:
        self.stop()

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

        listener = keyboard.GlobalHotKeys(
            {
                STOP_HOTKEY: debounce(on_stop),
                PAUSE_HOTKEY: debounce(on_pause),
            }
        )
        listener.start()
        self._listener = listener

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
