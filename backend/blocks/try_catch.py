from __future__ import annotations

SCHEMA = {
    "type": "try_catch",
    "label": "异常捕获",
    "category": "控制类",
    "description": (
        "尝试执行「尝试」分支；失败进入「捕获」，可选「收尾」。"
        "尝试/捕获链末端不要外接 next，留空即可回到本节点以进入收尾/继续。"
        "输出 raised / error，可供后续节点绑定。"
    ),
    "inputs": [],
    "outputs": [
        {"name": "raised", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, node=None, **kwargs):
    """Expose catch state; control flow is owned by the interpreter."""
    del params  # unused — ports are flow edges
    node_id = (node or {}).get("_id") or kwargs.get("node_id") or ""
    ctx = context if isinstance(context, dict) else {}
    return {
        "raised": bool(ctx.get(f"{node_id}.raised", False)),
        "error": str(ctx.get(f"{node_id}.error", "") or ""),
    }
