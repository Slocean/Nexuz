from __future__ import annotations

from typing import Any

SCHEMA = {
    "type": "loop_foreach",
    "label": "按数组循环",
    "category": "控制类",
    "inputs": [
        {
            "name": "collection",
            "type": "string",
            "label": "数组",
            "default": "",
            "placeholder": "$items 或 {{node.list}}",
        },
        {
            "name": "item_var",
            "type": "string",
            "label": "当前项变量名",
            "default": "$item",
            "bindable": False,
            "placeholder": "$item",
        },
    ],
    "outputs": [
        {"name": "index", "type": "number"},
        {"name": "item", "type": "any"},
        {"name": "length", "type": "number"},
    ],
}


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    # Single scalar → one-element list (convenient for ad-hoc binds)
    return [value]


def _normalize_item_var(raw: Any) -> str:
    name = str(raw or "$item").strip() or "$item"
    if not name.startswith("$"):
        name = f"${name.lstrip('$')}"
    return name


def inject_item_var(context: dict, item_var: str, item: Any) -> None:
    """Write current element into context under $name and bare name."""
    key = _normalize_item_var(item_var)
    context[key] = item
    context[key.lstrip("$")] = item


def handler(params, context, node=None, **kwargs):
    """Expose 0-based index + current item (counter before decide_next increments)."""
    node_id = (node or {}).get("_id") or kwargs.get("node_id") or ""
    counter_key = f"__loop_{node_id}__counter"
    ctx = context if isinstance(context, dict) else {}
    index = int(ctx.get(counter_key, 0) or 0)
    items = _as_list(params.get("collection"))
    item = items[index] if 0 <= index < len(items) else None
    item_var = _normalize_item_var(params.get("item_var"))
    if isinstance(context, dict):
        inject_item_var(context, item_var, item)
    return {"index": index, "item": item, "length": len(items)}
