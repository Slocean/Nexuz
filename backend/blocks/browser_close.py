from __future__ import annotations

from backend.core.browser.session import close_browser_session

SCHEMA = {
    "type": "browser_close",
    "label": "关闭浏览器",
    "category": "浏览器",
    "inputs": [],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    try:
        close_browser_session(force=True)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
