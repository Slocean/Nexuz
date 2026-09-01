"""Browser engine layer: CDP / DrissionPage backends behind one interface.

Blocks use `browser_op()` to get the live engine; the interpreter closes the
session at flow boundaries unless browser.keep_alive is set.
"""

from backend.core.browser.config import get_browser_config, set_browser_config
from backend.core.browser.session import browser_op, close_browser_session, get_engine, session_status

__all__ = [
    "browser_op",
    "close_browser_session",
    "get_browser_config",
    "get_engine",
    "session_status",
    "set_browser_config",
]
