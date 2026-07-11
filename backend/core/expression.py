"""Safe expression evaluator for if_condition / loop_while (no arbitrary eval)."""

from __future__ import annotations

import re
from typing import Any

from .variable_resolver import resolve_value

OPS = ("==", "!=", ">=", "<=", ">", "<", "contains")


def evaluate_expression(expression: str, context: dict[str, Any]) -> bool:
    if expression is None:
        return False
    expr = str(expression).strip()
    if not expr:
        return False

    resolved = resolve_value(expr, context)
    if isinstance(resolved, bool):
        return resolved
    if isinstance(resolved, (int, float)) and not isinstance(resolved, bool):
        return resolved != 0

    for op in OPS:
        pattern = re.compile(rf"^(.*?)\s*{re.escape(op)}\s*(.*)$", re.DOTALL)
        m = pattern.match(expr)
        if not m:
            continue
        left_raw, right_raw = m.group(1).strip(), m.group(2).strip()
        left = resolve_value(left_raw, context)
        right = _parse_rhs(right_raw, context)
        return _compare(left, right, op)

    if isinstance(resolved, str):
        low = resolved.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no", ""):
            return False
        return bool(resolved)
    return bool(resolved)


def _parse_rhs(raw: str, context: dict[str, Any]) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        inner = raw[1:-1]
        return resolve_value(inner, context) if ("{{" in inner or inner.startswith("$")) else inner
    return resolve_value(raw, context)


def _compare(left: Any, right: Any, op: str) -> bool:
    if op == "contains":
        return str(right) in str(left)

    left_n, right_n = _try_number(left), _try_number(right)
    if left_n is not None and right_n is not None and op in ("==", "!=", ">", "<", ">=", "<="):
        left, right = left_n, right_n
    else:
        left, right = str(left), str(right)

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    return False


def _try_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None
