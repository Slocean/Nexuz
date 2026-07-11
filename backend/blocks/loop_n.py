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
    node_id = (node or {}).get("_id") or ""
    # index comes from interpreter counter after decide; expose current for body
    # Before body runs, counter is already incremented in decide_next — for first entry
    # handler runs once per loop decision. We store counter in context by node id from kwargs.
    # Interpreter calls handler then decide_next; for loop nodes we just echo times.
    return {"index": int(params.get("times", 0) or 0)}
