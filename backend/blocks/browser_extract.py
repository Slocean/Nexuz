from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_extract",
    "description": "按 CSS 选择器批量提取浏览器元素的文本/属性/矩形。",
    "label": "浏览器提取",
    "category": "浏览器",
    "inputs": [
        {
            "name": "selector",
            "type": "string",
            "label": "CSS 选择器",
            "default": "",
            "placeholder": "例如 .item h2 或 a[href]",
            "bindable": True,
        },
        {
            "name": "attr",
            "type": "string",
            "label": "附加属性",
            "default": "",
            "placeholder": "可选，如 data-id",
        },
        {
            "name": "max_items",
            "type": "number",
            "label": "最多提取条数",
            "default": 200,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "items", "type": "array"},
        {"name": "count", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    selector = str(params.get("selector") or "").strip()
    attr = str(params.get("attr") or "").strip()
    try:
        max_items = int(params.get("max_items") or 200)
    except (TypeError, ValueError):
        max_items = 200

    def op(eng):
        items = eng.extract(selector, attr=attr, max_items=max(1, max_items))
        return {"items": items, "count": len(items)}

    return call_engine(op)
