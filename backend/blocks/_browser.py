"""Shared plumbing for browser_* blocks: single engine-op wrapper."""

from __future__ import annotations

from typing import Any, Callable


def call_engine(fn: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    """Run one operation against the live browser engine.

    Returns {"ok": True, **data} on success, {"ok": False, "error": ...} on
    any failure (BrowserError, timeout, closed session, bad params).
    """
    from backend.core.browser.session import browser_op

    try:
        with browser_op() as engine:
            data = fn(engine) or {}
        out = {"ok": True}
        out.update(data)
        return out
    except Exception as exc:  # noqa: BLE001 - blocks surface errors as outputs
        return {"ok": False, "error": str(exc)}


def default_screenshot_path(prefix: str = "page"):
    from backend.paths import get_data_dir

    shots = get_data_dir(create=True) / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    from time import strftime

    return shots / f"{prefix}_{strftime('%Y%m%d_%H%M%S')}.png"
