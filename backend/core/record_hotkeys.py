"""Global hotkey to stop recording (works for coord + Frida, even if window hidden)."""

from __future__ import annotations

import threading
import time
from typing import Callable

from backend.core.hotkey_prefs import get_record_stop_hotkey, to_pynput_hotkey


class RecordStopHotkeyWatcher:
    def __init__(self) -> None:
        self._listener = None
        self._lock = threading.Lock()
        self._last_fire = 0.0

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(self, on_stop: Callable[[], None] | None = None) -> None:
        self.stop()
        if on_stop is None:
            return

        def debounce() -> None:
            now = time.monotonic()
            with self._lock:
                if now - self._last_fire < 0.4:
                    return
                self._last_fire = now
            try:
                on_stop()
            except Exception:
                pass

        try:
            from pynput import keyboard
        except Exception:
            return

        binding = to_pynput_hotkey(get_record_stop_hotkey())
        try:
            listener = keyboard.GlobalHotKeys({binding: debounce})
            listener.start()
            self._listener = listener
        except Exception:
            self._listener = None

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass


_watcher: RecordStopHotkeyWatcher | None = None


def get_record_stop_hotkeys() -> RecordStopHotkeyWatcher:
    global _watcher
    if _watcher is None:
        _watcher = RecordStopHotkeyWatcher()
    return _watcher
