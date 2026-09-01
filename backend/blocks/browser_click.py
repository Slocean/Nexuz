from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_click",
    "label": "浏览器点击",
    "category": "浏览器",
    "inputs": [
        {
            "name": "selector",
            "type": "string",
            "label": "CSS 选择器",
            "default": "",
            "placeholder": "例如 #submit-btn",
            "bindable": True,
        },
        {
            "name": "use_js",
            "type": "boolean",
            "label": "用页面 JS 点击",
            "default": False,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    selector = str(params.get("selector") or "").strip()
    use_js = bool(params.get("use_js"))

    def op(eng):
        pos = eng.click(selector, use_js=use_js)
        return {"x": pos.get("x", 0), "y": pos.get("y", 0)}

    return call_engine(op)
