"""Best-effort restrictions for trusted python_script code; not a security sandbox."""

from __future__ import annotations

import builtins as _builtins
import io
from types import MappingProxyType
from typing import Any

ALLOWED_MODULES = frozenset(
    {
        "json",
        "math",
        "re",
        "datetime",
        "time",
        "random",
        "collections",
        "itertools",
    }
)

_SAFE_BUILTIN_NAMES = (
    "True",
    "False",
    "None",
    "abs",
    "all",
    "any",
    "bool",
    "chr",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hasattr",
    "hash",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "ord",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "StopIteration",
)


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = str(name or "").split(".", 1)[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(f"不允许导入模块: {name}（白名单: {', '.join(sorted(ALLOWED_MODULES))}）")
    return _builtins.__import__(name, globals, locals, fromlist, level)


def _make_builtins(print_fn) -> dict[str, Any]:
    ns: dict[str, Any] = {"__import__": _safe_import}
    for name in _SAFE_BUILTIN_NAMES:
        if name == "print":
            ns["print"] = print_fn
            continue
        if hasattr(_builtins, name):
            ns[name] = getattr(_builtins, name)
    return ns


def run_user_script(
    code: str,
    *,
    context: dict | None = None,
    inputs: dict | None = None,
) -> dict[str, Any]:
    """
    Execute user code in a restricted environment.

    Injected names: context (read-only), inputs (dict), out (writable dict).
    Returns {ok, result, error, printed}.
    """
    raw = str(code or "")
    if not raw.strip():
        return {"ok": False, "result": None, "error": "脚本不能为空", "printed": ""}

    buf = io.StringIO()

    def _print(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs.setdefault("file", buf)
        return _builtins.print(*args, **kwargs)

    ctx_src = context if isinstance(context, dict) else {}
    try:
        ctx_view = MappingProxyType(dict(ctx_src))
    except Exception:
        ctx_view = MappingProxyType({})

    in_map = dict(inputs) if isinstance(inputs, dict) else {}
    out: dict[str, Any] = {}

    g: dict[str, Any] = {
        "__builtins__": _make_builtins(_print),
        "__name__": "nexuz_user_script",
    }
    loc: dict[str, Any] = {
        "context": ctx_view,
        "inputs": in_map,
        "out": out,
    }

    try:
        compiled = compile(raw, "<python_script>", "exec")
        exec(compiled, g, loc)  # noqa: S102 — intentional trusted-code execution
    except Exception as exc:
        return {
            "ok": False,
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
            "printed": buf.getvalue(),
        }

    # Prefer out from locals if reassigned
    final_out = loc.get("out", out)
    if not isinstance(final_out, dict):
        return {
            "ok": False,
            "result": None,
            "error": "out 必须是 dict",
            "printed": buf.getvalue(),
        }

    ok = True
    error = ""
    if "ok" in final_out:
        ok = bool(final_out["ok"])
    if final_out.get("error"):
        error = str(final_out["error"])
        if "ok" not in final_out:
            ok = False

    if "result" in final_out:
        result = final_out["result"]
    elif final_out:
        result = {k: v for k, v in final_out.items() if k not in ("ok", "error")}
        if not result:
            result = None
    else:
        result = None

    return {
        "ok": ok,
        "result": result,
        "error": error,
        "printed": buf.getvalue(),
    }
