"""BrowserEngine: the interface every browser backend implements.

All methods block until done (handlers already run on worker threads) and
return JSON-compatible dicts. Runtime failures raise BrowserError subclasses;
parameter problems raise ValueError. Blocks translate exceptions into
{"ok": False, "error": ...} results.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any


def element_record(el: dict[str, Any], attr: str = "") -> dict[str, Any]:
    """Normalize one extracted element dict coming back from evaluate()."""
    rec: dict[str, Any] = {
        "text": str(el.get("text") or ""),
        "value": el.get("value"),
        "href": el.get("href"),
    }
    if attr:
        rec["attr"] = el.get("attr")
    rect = el.get("rect")
    if isinstance(rect, dict):
        rec["rect"] = {
            k: float(rect.get(k) or 0) for k in ("x", "y", "width", "height")
        }
    return rec


class BrowserEngine(abc.ABC):
    """One browser instance (process + page). Not thread-safe by itself;
    the session manager serializes access."""

    launched: bool = False

    @abc.abstractmethod
    def launch(self, *, headless: bool, user_data_dir: Path, binary_path: str = "") -> None:
        """Start the browser process and connect. Idempotent: no-op when alive."""

    @abc.abstractmethod
    def close(self) -> None:
        """Terminate the browser process. Idempotent."""

    @abc.abstractmethod
    def is_alive(self) -> bool: ...

    @abc.abstractmethod
    def navigate(self, url: str, timeout_ms: int = 30000) -> dict[str, Any]:
        """Navigate the active page and wait for load. Returns {"url","title"}."""

    @abc.abstractmethod
    def current_url(self) -> str: ...

    @abc.abstractmethod
    def title(self) -> str: ...

    @abc.abstractmethod
    def eval_js(self, expression: str, timeout_ms: int = 15000) -> Any:
        """Evaluate JS in the page, return the JSON value."""

    @abc.abstractmethod
    def extract(self, selector: str, attr: str = "", max_items: int = 200) -> list[dict[str, Any]]:
        """Collect text/value/attr/rect for all elements matching selector."""

    @abc.abstractmethod
    def click(self, selector: str, timeout_ms: int = 10000, use_js: bool = False) -> dict[str, Any]:
        """Click first match. Returns {"x","y"} of the click point."""

    @abc.abstractmethod
    def fill(self, selector: str, text: str, timeout_ms: int = 10000) -> dict[str, Any]: ...

    @abc.abstractmethod
    def screenshot(
        self, save_path: str | None = None, full_page: bool = True
    ) -> dict[str, Any]:
        """Capture PNG. Returns {"path","width","height"}."""

    @abc.abstractmethod
    def wait_document(self, state: str, timeout_ms: int = 30000) -> dict[str, Any]:
        """Wait until document.readyState reaches state ("interactive"/"complete")."""
