from __future__ import annotations

from pathlib import Path

SCHEMA = {
    "type": "call_subflow",
    "label": "调用子流程",
    "category": "控制类",
    "inputs": [
        {
            "name": "subflow_path",
            "type": "string",
            "label": "子流程 .flow.json 路径",
            "default": "",
        },
        {
            "name": "inherit_variables",
            "type": "select",
            "label": "继承父流程变量",
            "options": ["true", "false"],
            "default": "true",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "context_keys", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    """Run another flow file synchronously inside current interpreter thread."""
    import json

    from backend.core.interpreter import FlowInterpreter
    from backend.core.registry import get_handler  # noqa: F401 — ensure blocks ready

    path = str(params.get("subflow_path") or "").strip()
    if not path:
        raise ValueError("请指定子流程路径 subflow_path")
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"子流程不存在: {path}")

    flow = json.loads(p.read_text(encoding="utf-8"))
    inherit = str(params.get("inherit_variables", "true")).lower() != "false"

    # Nested sync execution: reuse decide/handler logic without starting a new thread
    interp = FlowInterpreter(emit=kwargs.get("emit"))
    # Inject parent context variables into subflow variables
    if inherit:
        parent_vars = {k: v for k, v in context.items() if str(k).startswith("$")}
        flow_vars = dict(flow.get("variables") or {})
        flow_vars.update(parent_vars)
        flow = {**flow, "variables": flow_vars}

    # Run nested execute synchronously
    sub_ctx = interp._execute(flow)
    # Merge key outputs back (prefixed)
    for k, v in sub_ctx.items():
        if str(k).startswith("$") or "." in str(k):
            context[f"sub.{k}"] = v
    return {"ok": True, "context_keys": len(sub_ctx)}
