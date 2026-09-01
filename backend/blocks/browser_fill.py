from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_fill",
    "label": "浏览器填充",
    "category": "浏览器",
    "inputs": [
        {
            "name": "selector",
            "type": "string",
            "label": "CSS 选择器",
            "default": "",
            "placeholder": "例如 input[name='q']",
            "bindable": True,
        },
        {
            "name": "text",
            "type": "string",
            "label": "填充内容",
            "default": "",
            "ui": "textarea",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    selector = str(params.get("selector") or "").strip()
    text = "" if params.get("text") is None else str(params.get("text"))

    def op(eng):
        return eng.fill(selector, text)

    return call_engine(op)
