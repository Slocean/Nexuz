"""Trim runtime payloads before IPC / long-lived context retention."""

from __future__ import annotations

from typing import Any

_MAX_STR = 240
_MAX_LIST = 24
_MAX_DICT_KEYS = 40
_MAX_DEPTH = 4
_HEAVY_KEYS = frozenset({"boxes", "box", "image", "bitmap", "pixels", "raw", "screenshot"})


def summarize_value(value: Any, *, depth: int = 0, key: str | None = None) -> Any:
    """Return a compact, JSON-serializable preview of a runtime value."""
    if depth >= _MAX_DEPTH:
        return "…"
    if key and key.lower() in _HEAVY_KEYS:
        if isinstance(value, list):
            return {"_omitted": "boxes", "count": len(value)}
        if value is None:
            return None
        return {"_omitted": key}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _MAX_STR:
            return value
        return f"{value[:_MAX_STR]}…(+{len(value) - _MAX_STR})"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_DICT_KEYS:
                out["…"] = f"+{len(value) - _MAX_DICT_KEYS} keys"
                break
            out[str(k)] = summarize_value(v, depth=depth + 1, key=str(k))
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)
        head = [summarize_value(v, depth=depth + 1) for v in items[:_MAX_LIST]]
        if len(items) > _MAX_LIST:
            head.append(f"…(+{len(items) - _MAX_LIST})")
        return head
    return str(value)[:_MAX_STR]


def summarize_params(params: dict | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    return {str(k): summarize_value(v, key=str(k)) for k, v in params.items()}


def summarize_result(result: dict | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {str(k): summarize_value(v, key=str(k)) for k, v in result.items()}


def compact_context_value(key: str, value: Any) -> Any:
    """Keep context bindable but drop heavy OCR/geometry payloads."""
    k = str(key)
    leaf = k.rsplit(".", 1)[-1].lower()
    if leaf == "boxes" and isinstance(value, list):
        # Keep text + light AABB/center for binding; drop heavy polygons.
        compact = []
        for item in value[:80]:
            if not isinstance(item, dict):
                continue
            entry: dict[str, Any] = {
                "text": str(item.get("text") or "")[:120],
                "confidence": item.get("confidence"),
            }
            for geom_key in ("left", "top", "width", "height", "cx", "cy"):
                if geom_key in item and item[geom_key] is not None:
                    entry[geom_key] = item[geom_key]
            compact.append(entry)
        return compact
    if leaf in ("box", "image", "bitmap", "pixels") and isinstance(value, (list, dict)):
        return None
    return value
