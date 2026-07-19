from __future__ import annotations

from backend.core.worker_client import run_isolated
from backend.core.variable_resolver import resolve_value

SCHEMA = {
    "type": "python_script",
    "label": "Python 脚本（仅可信代码）",
    "category": "系统类",
    "description": "仅可信代码：隔离 worker 默认阻断网络、子进程和文件写入，但仍非完整安全沙箱。",
    "trust_tier": "trusted_code_only",
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
        {
            "name": "timeout_seconds",
            "type": "number",
            "label": "最长运行秒数",
            "default": 10,
            "min": 1,
            "max": 60,
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

    try:
        timeout_seconds = min(60.0, max(1.0, float(params.get("timeout_seconds") or 10)))
    except (TypeError, ValueError):
        timeout_seconds = 10.0
    response = run_isolated(
        {
            "kind": "script",
            "code": str(code),
            "context": ctx,
            "inputs": inputs,
        },
        timeout_seconds=timeout_seconds,
        should_stop=kwargs.get("should_stop"),
    )
    if not response.get("ok"):
        return {
            "ok": False,
            "result": None,
            "error": response.get("error") or "Python worker 执行失败",
            "printed": response.get("worker_stdout") or "",
        }
    res = response.get("result")
    if not isinstance(res, dict):
        return {
            "ok": False,
            "result": None,
            "error": "Python worker 返回格式无效",
            "printed": response.get("worker_stdout") or "",
        }
    return {
        "ok": bool(res.get("ok")),
        "result": res.get("result"),
        "error": res.get("error") or "",
        "printed": res.get("printed") or "",
    }
