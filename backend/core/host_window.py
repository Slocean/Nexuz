"""Host-window helpers so playback mouse events can reach windows below Nexuz.

The compact run-monitor is topmost in the top-right corner. Without temporarily
yielding hit-testing, pyautogui clicks land on Nexuz instead of the target app
when coordinates overlap that panel — a common failure mode for multi-click
sequences aimed at the right side of the screen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

_Begin = Callable[[], None]
_End = Callable[[], None]

_begin: _Begin | None = None
_end: _End | None = None


def register_mouse_yield(begin: _Begin | None, end: _End | None) -> None:
    """Wire Api callbacks (called once when the main window is ready)."""
    global _begin, _end
    _begin = begin
    _end = end


@contextmanager
def yield_host_mouse() -> Iterator[None]:
    """Let OS hit-testing skip Nexuz for the duration of a mouse action."""
    begin, end = _begin, _end
    if begin is None:
        yield
        return
    begin()
    try:
        yield
    finally:
        if end is not None:
            end()
