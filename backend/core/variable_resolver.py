"""Variable interpolation for FlowModel params."""

from __future__ import annotations

import re
from typing import Any

VAR_PATTERN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
# $name or $name.0.field (path segments: word or digits)
DOLLAR_PATTERN = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)")
# 转义：$$name → 字面量 $name（不做变量替换）。$$ 后必须紧跟变量形态的 token，
# 避免 "$$ 100 元" 这类普通文本被误当转义。
DOLLAR_ESCAPE_PATTERN = re.compile(r"\$\$(\$?[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)")
_ESCAPE_SENTINEL = "\x00nx-esc-\x00"


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


_COORD_LEAF_SUFFIXES = (".x", ".y", ".cx", ".cy")


def infer_window_target_from_coord_binding(
    raw_params: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """When click x/y is ``{{ocr.x}}`` / ``{{ocr.matches.0.x}}``, pull sibling window_target.

    OCR window_client mode attaches window_target next to geometry; users usually only
    bind x/y onto the click node.
    """
    if not isinstance(raw_params, dict) or not isinstance(context, dict):
        return None

    def _pick_wt(wt: Any) -> dict[str, Any] | None:
        if isinstance(wt, dict) and wt.get("point_norm") is not None:
            return wt
        if isinstance(wt, list):
            for item in wt:
                if isinstance(item, dict) and item.get("point_norm") is not None:
                    return item
        return None

    def _from_path(path: str) -> dict[str, Any] | None:
        path = str(path or "").strip()
        if not path:
            return None
        lower = path.lower()
        bases: list[str] = []
        for suffix in _COORD_LEAF_SUFFIXES:
            if lower.endswith(suffix):
                bases.append(path[: -len(suffix)])
                break
        if not bases:
            bases.append(path)

        for base in bases:
            found = _pick_wt(_lookup(f"{base}.window_target", context))
            if found is not None:
                return found

        # Node-level fallback only when NOT addressing a specific matches[N] entry.
        # Otherwise ocr.matches.1.x must not inherit ocr.window_target (primary hit).
        if ".matches." not in lower:
            head = path.split(".", 1)[0]
            if head and head not in bases:
                found = _pick_wt(_lookup(f"{head}.window_target", context))
                if found is not None:
                    return found
        return None

    for key in ("x", "y", "from_x", "from_y", "to_x", "to_y"):
        raw = raw_params.get(key)
        if not isinstance(raw, str):
            continue
        m = VAR_PATTERN.fullmatch(raw.strip())
        if not m:
            continue
        found = _from_path(m.group(1))
        if found is not None:
            return found
    return None


def attach_inferred_window_target(
    raw_params: dict[str, Any] | None,
    resolved_params: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fill / override window_target for window_client clicks bound from OCR outputs.

    Prefer the OCR-bound window_target (with OCR-time point_norm) over a stale
    take-point left on the click node.

    Do NOT recompute point_norm from bound screen x/y at click time: those abs
    coords go stale if the window moved/activated, and retargeting them against
    the new client origin shifts clicks left/up of the real text.
    """
    params = dict(resolved_params or {})
    mode = str(params.get("coordinate_mode") or params.get("coord_mode") or "").strip()
    if mode != "window_client":
        return params

    nested = params.get("coord") if isinstance(params.get("coord"), dict) else None
    inferred = infer_window_target_from_coord_binding(raw_params, context)
    if isinstance(inferred, dict) and inferred.get("point_norm") is not None:
        params["window_target"] = inferred
        if nested is not None:
            params["coord"] = {
                **nested,
                "window_target": inferred,
                "coordinate_mode": "window_client",
            }
        return params

    # No OCR bind → keep node / nested take-point target.
    if isinstance(params.get("window_target"), dict):
        return params
    if nested and isinstance(nested.get("window_target"), dict):
        params["window_target"] = nested["window_target"]
    return params


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
    # $$name → 字面量 $name：先 stash，替换完成后再还原，保证不参与变量解析
    escaped: list[str] = []

    def _stash(match: re.Match) -> str:
        escaped.append(match.group(1))
        return f"{_ESCAPE_SENTINEL}{len(escaped) - 1}{_ESCAPE_SENTINEL}"

    if DOLLAR_ESCAPE_PATTERN.search(text):
        text = DOLLAR_ESCAPE_PATTERN.sub(_stash, text)

    # Exact match {{node.field}} / {{node.matches.0.x}} → return raw typed value
    m = VAR_PATTERN.fullmatch(text.strip())
    if m:
        val = _lookup(m.group(1), context)
        out = "" if val is None else val
        return _restore_escapes(out, escaped) if isinstance(out, str) else out

    # Exact $name or $name.0.field → typed value (not stringified)
    m = DOLLAR_PATTERN.fullmatch(text.strip())
    if m:
        val = _lookup(m.group(1), context)
        out = "" if val is None else val
        return _restore_escapes(out, escaped) if isinstance(out, str) else out

    def repl_brace(match: re.Match) -> str:
        val = _lookup(match.group(1), context)
        return "" if val is None else str(val)

    def repl_dollar(match: re.Match) -> str:
        val = _lookup(match.group(1), context)
        return "" if val is None else str(val)

    out = VAR_PATTERN.sub(repl_brace, text)
    out = DOLLAR_PATTERN.sub(repl_dollar, out)
    return _restore_escapes(out, escaped)


def _restore_escapes(value: str, escaped: list[str]) -> str:
    if not escaped:
        return value
    for i, name in enumerate(escaped):
        value = value.replace(f"{_ESCAPE_SENTINEL}{i}{_ESCAPE_SENTINEL}", f"${name}")
    return value
