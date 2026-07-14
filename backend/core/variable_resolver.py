"""Variable interpolation for FlowModel params."""

from __future__ import annotations

import re
from typing import Any

VAR_PATTERN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
# $name or $name.0.field (path segments: word or digits)
DOLLAR_PATTERN = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)")


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


def _dig(root: Any, parts: list[str]) -> Any:
    cur = root
    for part in parts:
        if cur is None:
            return None
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            # numeric key stored as int in some payloads
            if part.isdigit() and int(part) in cur:
                cur = cur[int(part)]
                continue
            return None
        if isinstance(cur, (list, tuple)):
            if not part.isdigit():
                return None
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue
        return None
    return cur


def _lookup(key: str, context: dict[str, Any]) -> Any:
    """Lookup exact key or dotted path like nodeId.matches.0.x / $var.field."""
    key = key.strip()
    if not key:
        return None

    # Exact hit first (covers nodeId.field and $name)
    if key in context:
        return context[key]
    if key.startswith("$") and key[1:] in context:
        return context[key[1:]]
    if not key.startswith("$") and f"${key}" in context:
        return context[f"${key}"]

    # Path: try longest exact prefix then dig
    parts = [p for p in key.split(".") if p != ""]
    if len(parts) < 2:
        return None

    # nodeId.field... → context["nodeId.field"] then dig rest
    # Also support $var.0.x with root $var or var
    for i in range(len(parts) - 1, 0, -1):
        head = ".".join(parts[:i])
        root = None
        if head in context:
            root = context[head]
        elif head.startswith("$") and head[1:] in context:
            root = context[head[1:]]
        elif not head.startswith("$") and f"${head}" in context:
            root = context[f"${head}"]
        if root is not None:
            return _dig(root, parts[i:])

    # Fallback: first segment as bare/$ var, rest as path
    first = parts[0]
    root = None
    if first in context:
        root = context[first]
    elif first.startswith("$") and first[1:] in context:
        root = context[first[1:]]
    elif f"${first}" in context:
        root = context[f"${first}"]
    if root is not None:
        return _dig(root, parts[1:])
    return None


def _resolve_string(text: str, context: dict[str, Any]) -> Any:
    # Exact match {{node.field}} / {{node.matches.0.x}} → return raw typed value
    m = VAR_PATTERN.fullmatch(text.strip())
    if m:
        val = _lookup(m.group(1), context)
        return "" if val is None else val

    # Exact $name or $name.0.field → typed value (not stringified)
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
