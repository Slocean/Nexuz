"""Trim runtime payloads before IPC / long-lived context retention."""

from __future__ import annotations

from typing import Any

_MAX_STR = 240
_MAX_LIST = 24
_MAX_DICT_KEYS = 40
_MAX_DEPTH = 6
_HEAVY_KEYS = frozenset({"box", "image", "bitmap", "pixels", "raw", "screenshot"})
_LIGHT_LIST_KEYS = frozenset({"boxes", "matches"})
_GEOM_KEYS = ("left", "top", "width", "height", "cx", "cy", "x", "y")


def _compact_ocr_item(item: dict[str, Any], *, as_box: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if "text" in item or as_box:
        entry["text"] = str(item.get("text") or "")[:120]
    if "confidence" in item:
        entry["confidence"] = item.get("confidence")
    if "query" in item:
        entry["query"] = str(item.get("query") or "")[:120]
    if "matched_text" in item:
        mt = item.get("matched_text")
        if isinstance(mt, list):
            entry["matched_text"] = [str(x or "")[:80] for x in mt[:24]]
        else:
            entry["matched_text"] = str(mt or "")[:120]
    if "found" in item:
        entry["found"] = bool(item.get("found"))
    if "count" in item:
        entry["count"] = item.get("count")
    for geom_key in _GEOM_KEYS:
        if geom_key not in item or item[geom_key] is None:
            continue
        val = item[geom_key]
        if isinstance(val, (list, tuple)):
            nums = []
            for x in list(val)[:24]:
                if isinstance(x, (bool, int, float)):
                    nums.append(x)
                else:
                    try:
                        nums.append(int(round(float(x))))
                    except (TypeError, ValueError):
                        continue
            entry[geom_key] = nums
        elif isinstance(val, (bool, int, float)):
            entry[geom_key] = val
        else:
            try:
                entry[geom_key] = int(round(float(val)))
            except (TypeError, ValueError):
                pass
    return entry


def _compact_ocr_list(value: list[Any], *, as_box: bool) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in value[:80]:
        if isinstance(item, dict):
            compact.append(_compact_ocr_item(item, as_box=as_box))
    return compact


def summarize_value(value: Any, *, depth: int = 0, key: str | None = None) -> Any:
    """Return a compact, JSON-serializable preview of a runtime value."""
    # Scalars always pass through — never replace numbers with "…" due to depth.
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _MAX_STR:
            return value
        return f"{value[:_MAX_STR]}…(+{len(value) - _MAX_STR})"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    leaf = str(key).lower() if key else ""
    if leaf in _LIGHT_LIST_KEYS and isinstance(value, list):
        return _compact_ocr_list(value, as_box=(leaf == "boxes"))
    if leaf in _HEAVY_KEYS:
        if isinstance(value, list):
            return {"_omitted": leaf, "count": len(value)}
        return None if value is None else {"_omitted": leaf}

    if depth >= _MAX_DEPTH:
        return "…"

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
        # Homogeneous number lists (multi-hit OCR coords) stay numeric.
        if items and all(isinstance(v, (bool, int, float)) or v is None for v in items):
            head = list(items[:_MAX_LIST])
            if len(items) > _MAX_LIST:
                head.append(f"…(+{len(items) - _MAX_LIST})")
            return head
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
    if leaf in ("boxes", "matches") and isinstance(value, list):
        return _compact_ocr_list(value, as_box=(leaf == "boxes"))
    if leaf in ("box", "image", "bitmap", "pixels") and isinstance(value, (list, dict)):
        return None
    return value
