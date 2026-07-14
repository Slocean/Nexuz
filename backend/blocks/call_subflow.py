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
            "label": "子流程路径",
            "default": "",
            "placeholder": "xxx.flow.json",
        },
        {
            "name": "inherit_variables",
            "type": "select",
            "label": "继承父变量",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {
                "true": "是",
                "false": "否",
            },
        },
        {
            "name": "input_map",
            "type": "keymap",
            "label": "传入变量",
            "default": {},
            "ui": "input_map",
        },
        {
            "name": "output_map",
            "type": "keymap",
            "label": "取回变量",
            "default": {},
            "ui": "output_map",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "context_keys", "type": "number"},
    ],
}


def _normalize_var_key(name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    return n if n.startswith("$") else f"${n}"


def _lookup_sub(key: str, sub_ctx: dict):
    """Resolve a key from subflow context: $var | node.field | bare name."""
    k = str(key or "").strip()
    if not k:
        return None
    if k in sub_ctx:
        return sub_ctx[k]
    if k.startswith("$"):
        bare = k[1:]
        if bare in sub_ctx:
            return sub_ctx[bare]
        if k in sub_ctx:
            return sub_ctx[k]
    else:
        dollar = f"${k}"
        if dollar in sub_ctx:
            return sub_ctx[dollar]
    return None


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    """Run another flow file synchronously inside current interpreter thread."""
    import json

    from backend.core.interpreter import FlowInterpreter
    from backend.core.registry import get_handler  # noqa: F401 — ensure blocks ready
    from backend.core.variable_resolver import resolve_value

    path = str(params.get("subflow_path") or "").strip()
    if not path:
        raise ValueError("请指定子流程路径 subflow_path")
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"子流程不存在: {path}")

    flow = json.loads(p.read_text(encoding="utf-8"))
    inherit = str(params.get("inherit_variables", "true")).lower() != "false"

    interp = FlowInterpreter(emit=kwargs.get("emit"))
    # Nested run must honor parent pause/stop (e.g. delay inside subflow).
    interp.bind_parent_controls(should_stop=should_stop, cooperate=cooperate)
    flow_vars = dict(flow.get("variables") or {})

    if inherit:
        parent_vars = {k: v for k, v in context.items() if str(k).startswith("$")}
        flow_vars.update(parent_vars)

    # Explicit input map: subflow $name ← resolved parent value
    raw_in = params.get("input_map") or {}
    if isinstance(raw_in, dict):
        for sub_key, parent_val in raw_in.items():
            nk = _normalize_var_key(str(sub_key))
            if not nk:
                continue
            # params already resolved by interpreter, but nested map values
            # may still be refs if resolve_variables walked them — double-safe
            resolved = resolve_value(parent_val, context)
            flow_vars[nk] = resolved
            flow_vars[nk.lstrip("$")] = resolved

    flow = {**flow, "variables": flow_vars}

    sub_ctx = interp._execute(flow)

    # Do not mirror the entire sub-context into the parent (can be huge with OCR etc.).
    # Only expose a light key list for discovery; values come via output_map.
    discoverable = [
        str(k)
        for k in sub_ctx.keys()
        if str(k).startswith("$") or "." in str(k)
    ]
    context["sub.__keys__"] = discoverable[:200]
    # Keep $variables only (usually small) under sub.$name for optional binding.
    for k, v in sub_ctx.items():
        sk = str(k)
        if sk.startswith("$"):
            context[f"sub.{sk}"] = v

    # Explicit output map: parent $name ← subflow key
    raw_out = params.get("output_map") or {}
    if isinstance(raw_out, dict):
        for parent_key, sub_key in raw_out.items():
            pk = _normalize_var_key(str(parent_key))
            if not pk:
                continue
            val = _lookup_sub(str(sub_key), sub_ctx)
            if val is None:
                val = context.get(f"sub.{sub_key}")
            context[pk] = val
            context[pk.lstrip("$")] = val

    # Drop the heavy sub_ctx reference ASAP for GC in long parent runs.
    key_count = len(sub_ctx)
    del sub_ctx
    return {"ok": True, "context_keys": key_count}
