from __future__ import annotations

from backend.blocks._script_sandbox import run_user_script
from backend.core.variable_resolver import resolve_value

SCHEMA = {
    "type": "python_script",
    "label": "Python 脚本",
    "category": "系统类",
    "inputs": [
        {
            "name": "code",
            "type": "string",
            "label": "脚本",
            "default": 'out["result"] = 1 + 1\nprint("sum=", out["result"])\n',
            "ui": "python_code",
            "placeholder": '写入 out 字典，例如 out["result"] = inputs.get("x")',
        },
        {
            "name": "inputs",
            "type": "keymap",
            "label": "注入变量",
            "default": {},
            "ui": "input_map",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "result", "type": "any"},
        {"name": "error", "type": "string"},
        {"name": "printed", "type": "string", "canvas": False},
    ],
}


def handler(params, context, **kwargs):
    code = params.get("code") or ""
    raw_inputs = params.get("inputs") or {}
    inputs: dict = {}
    ctx = context if isinstance(context, dict) else {}
    if isinstance(raw_inputs, dict):
        for key, value in raw_inputs.items():
            name = str(key or "").strip()
            if not name:
                continue
            inputs[name] = resolve_value(value, ctx)

    res = run_user_script(str(code), context=ctx, inputs=inputs)
    return {
        "ok": bool(res.get("ok")),
        "result": res.get("result"),
        "error": res.get("error") or "",
        "printed": res.get("printed") or "",
    }
