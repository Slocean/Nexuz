from __future__ import annotations

SCHEMA = {
    "type": "loop_n",
    "label": "固定次数循环",
    "category": "控制类",
    "inputs": [
        {"name": "times", "type": "number", "label": "次数", "default": 3},
    ],
    "outputs": [
        {"name": "index", "type": "number"},
    ],
}


def handler(params, context, node=None, **kwargs):
    """Expose 0-based iteration index (counter before decide_next increments)."""
    node_id = (node or {}).get("_id") or kwargs.get("node_id") or ""
    counter_key = f"__loop_{node_id}__counter"
    ctx = context if isinstance(context, dict) else {}
    index = int(ctx.get(counter_key, 0) or 0)
    return {"index": index}
