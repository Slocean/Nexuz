"""Process-level browser session singleton.

The session is the BrowserEngine instance: lazily launched on first use,
serialized by an op lock, and closed at flow boundaries unless keep_alive.
Rebuilds when the resolved engine signature (engine/headless/profile/binary)
changes so settings take effect without an app restart.
"""

from __future__ import annotations

import atexit
import importlib.util
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.core.browser.config import get_browser_config
from backend.core.browser.errors import BrowserError
from backend.core.browser.engine import BrowserEngine

_create_lock = threading.Lock()
_op_lock = threading.RLock()
_engine: BrowserEngine | None = None
_signature: tuple[str, bool, str, str] | None = None
_closed_by_default = True


def _resolve_engine_name(cfg: dict[str, Any]) -> str:
    choice = str(cfg.get("engine") or "auto").lower()
    if choice == "auto":
        return "drission" if importlib.util.find_spec("DrissionPage") is not None else "cdp"
    return choice


def _profile_dir(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("profile_dir") or "").strip()
    if raw:
        return Path(raw)
    from backend.paths import get_data_dir

    return get_data_dir(create=True) / "browser_profile"


def _new_engine(name: str) -> BrowserEngine:
    if name == "drission":
        from backend.core.browser.drission_backend import DrissionEngine

        return DrissionEngine()
    if name == "cdp":
        from backend.core.browser.cdp_backend import CdpEngine

        return CdpEngine()
    raise BrowserError(f"未知浏览器引擎: {name}")


def _signature_of(cfg: dict[str, Any], name: str) -> tuple[str, bool, str, str]:
    return (
        name,
        bool(cfg.get("headless", True)),
        str(_profile_dir(cfg)),
        str(cfg.get("edge_path") or ""),
    )


def get_engine() -> BrowserEngine:
    """Return the live engine, launching/rebuilding as needed. Holds _op_lock."""
    global _engine, _signature
    cfg = get_browser_config()
    name = _resolve_engine_name(cfg)
    sig = _signature_of(cfg, name)
    if _engine is not None and _signature == sig and _engine.is_alive():
        return _engine
    if _engine is not None:
        try:
            _engine.close()
        except Exception:
            pass
        _engine = None
    if name == "drission" and cfg.get("engine") == "drission" and importlib.util.find_spec("DrissionPage") is None:
        from backend.core.log_hub import build_log_row, get_app_log_manager

        try:
            get_app_log_manager().write_row(
                build_log_row(
                    "browser",
                    {"message": "DrissionPage 未安装，回退 CDP 引擎"},
                    message="DrissionPage 未安装，回退 CDP 引擎",
                    level="warning",
                )
            )
        except Exception:
            pass
        name = "cdp"
        sig = _signature_of(cfg, name)
    engine = _new_engine(name)
    engine.launch(
        headless=bool(cfg.get("headless", True)),
        user_data_dir=_profile_dir(cfg),
        binary_path=str(cfg.get("edge_path") or ""),
    )
    _engine = engine
    _signature = sig
    return engine


@contextmanager
def browser_op() -> Iterator[BrowserEngine]:
    """Serialize one browser operation and hand out the live engine."""
    with _op_lock:
        yield get_engine()


def session_status() -> dict[str, Any]:
    """Cheap status probe — never launches the browser.

    Alive 时附 quick_status()（url/title/tabs，引擎各自 best-effort，
    任何异常只省略字段，不阻塞 get_status 轮询）。
    """
    alive = bool(_engine is not None and _engine.is_alive())
    out: dict[str, Any] = {"alive": alive, "engine": (_signature[0] if alive and _signature else None)}
    if alive:
        try:
            out.update(_engine.quick_status())
        except Exception:
            pass
    return out


def close_browser_session(*, force: bool = False) -> None:
    """Flow-boundary cleanup: honors keep_alive unless force=True."""
    global _engine, _signature
    if _engine is None:
        return
    if not force and get_browser_config().get("keep_alive"):
        return
    with _op_lock:
        if _engine is None:
            return
        try:
            _engine.close()
        except Exception:
            pass
        _engine = None
        _signature = None


atexit.register(close_browser_session, force=True)
