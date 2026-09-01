from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_navigate",
    "label": "浏览器导航",
    "category": "浏览器",
    "inputs": [
        {
            "name": "url",
            "type": "string",
            "label": "网址",
            "default": "",
            "placeholder": "https://example.com",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "加载超时(ms)",
            "default": 30000,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "url", "type": "string"},
        {"name": "title", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    url = str(params.get("url") or "").strip()
    try:
        timeout_ms = int(params.get("timeout_ms") or 30000)
    except (TypeError, ValueError):
        timeout_ms = 30000

    def op(eng):
        data = eng.navigate(url, timeout_ms=max(1000, timeout_ms))
        return {"url": data.get("url", url), "title": data.get("title", "")}

    return call_engine(op)
