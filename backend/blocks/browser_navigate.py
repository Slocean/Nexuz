from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_navigate",
    "description": "导航到指定网址并等待加载完成，可选同时设定视口尺寸。",
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
        {
            "name": "viewport_width",
            "type": "number",
            "label": "视口宽度(px，0=不调整)",
            "default": 0,
        },
        {
            "name": "viewport_height",
            "type": "number",
            "label": "视口高度(px，0=不调整)",
            "default": 0,
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
    try:
        vp_w = int(float(params.get("viewport_width") or 0))
        vp_h = int(float(params.get("viewport_height") or 0))
    except (TypeError, ValueError):
        vp_w = vp_h = 0
    # 先校验再导航：参数不配对时不应产生导航副作用
    if (vp_w > 0) != (vp_h > 0):
        raise ValueError("viewport_width 与 viewport_height 需同时 >0（或都为 0 表示不调整）")

    def op(eng):
        from backend.blocks import browser_snapshot

        browser_snapshot.clear_refs(eng)
        data = eng.navigate(url, timeout_ms=max(1000, timeout_ms))
        if vp_w > 0:
            eng.set_viewport(vp_w, vp_h)
        return {"url": data.get("url", url), "title": data.get("title", "")}

    return call_engine(op)
