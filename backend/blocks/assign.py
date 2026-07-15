from __future__ import annotations

from backend.core.variable_resolver import resolve_value

SCHEMA = {
    "type": "assign",
    "label": "赋值变量",
    "category": "控制类",
    "inputs": [
        {
            "name": "mappings",
            "type": "keymap",
            "label": "变量映射",
            "default": {},
            "ui": "input_map",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "written", "type": "array", "canvas": False},
    ],
}


def _normalize_var_key(name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    return n if n.startswith("$") else f"${n}"


def handler(params, context, **kwargs):
    """Write resolved values into flow $variables for downstream binding."""
    raw = params.get("mappings") or {}
    written: list[str] = []
    if not isinstance(raw, dict):
        return {"ok": False, "written": written}

    ctx = context if isinstance(context, dict) else {}
    for var_name, value in raw.items():
        key = _normalize_var_key(str(var_name))
        if not key:
            continue
        # params are usually pre-resolved; resolve again for nested safety
        resolved = resolve_value(value, ctx)
        ctx[key] = resolved
        ctx[key.lstrip("$")] = resolved
        written.append(key)

    return {"ok": True, "written": written}
