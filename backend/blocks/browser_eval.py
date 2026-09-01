from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_eval",
    "label": "浏览器执行 JS",
    "category": "浏览器",
    "inputs": [
        {
            "name": "expression",
            "type": "string",
            "label": "JS 表达式",
            "default": "",
            "placeholder": "例如 document.querySelectorAll('p').length",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "超时(ms)",
            "default": 15000,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "result", "type": "any"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    expression = str(params.get("expression") or "").strip()
    try:
        timeout_ms = int(params.get("timeout_ms") or 15000)
    except (TypeError, ValueError):
        timeout_ms = 15000

    def op(eng):
        return {"result": eng.eval_js(expression, timeout_ms=max(500, timeout_ms))}

    return call_engine(op)
