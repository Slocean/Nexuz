"""Variable interpolation for FlowModel params."""

from __future__ import annotations

import re
from typing import Any

VAR_PATTERN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
DOLLAR_PATTERN = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, context)
    if isinstance(value, list):
        return [resolve_value(v, context) for v in value]
    if isinstance(value, dict):
        return {k: resolve_value(v, context) for k, v in value.items()}
    return value


def resolve_variables(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {k: resolve_value(v, context) for k, v in (params or {}).items()}


def _lookup(key: str, context: dict[str, Any]) -> Any:
    key = key.strip()
    if key.startswith("$"):
        key = key[1:]
    if key in context:
        return context[key]
    # allow $myVar stored as myVar or $myVar
    if f"${key}" in context:
        return context[f"${key}"]
    return None


def _resolve_string(text: str, context: dict[str, Any]) -> Any:
    # Exact match {{node.field}} → return raw typed value
    m = VAR_PATTERN.fullmatch(text.strip())
    if m:
        val = _lookup(m.group(1), context)
        return "" if val is None else val

    m = DOLLAR_PATTERN.fullmatch(text.strip())
    if m:
        val = _lookup(m.group(1), context)
        return "" if val is None else val

    def repl_brace(match: re.Match) -> str:
        val = _lookup(match.group(1), context)
        return "" if val is None else str(val)

    def repl_dollar(match: re.Match) -> str:
        val = _lookup(match.group(1), context)
        return "" if val is None else str(val)

    out = VAR_PATTERN.sub(repl_brace, text)
    out = DOLLAR_PATTERN.sub(repl_dollar, out)
    return out
