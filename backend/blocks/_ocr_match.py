"""Shared OCR text-match helpers: box AABB, match modes, multi-hit coords."""

from __future__ import annotations

import re
from typing import Any


def match_text(actual: str, expect: str, mode: str) -> bool:
    """Match `actual` against `expect` with contains / exact / regex."""
    mode = str(mode or "contains")
    expect = str(expect or "")
    actual = str(actual or "")
    if mode == "exact":
        return actual.strip() == expect.strip()
    if mode == "regex":
        try:
            return bool(re.search(expect, actual))
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
    if not expect:
        return False
    return expect in actual


def aabb_from_polygon(
    box: list | None,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> dict[str, int]:
    """Convert polygon points (local) to screen-absolute AABB + center."""
    xs: list[float] = []
    ys: list[float] = []
    try:
        for pt in box or []:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                xs.append(float(pt[0]))
                ys.append(float(pt[1]))
    except (TypeError, ValueError):
        pass
    if not xs or not ys:
        return {
            "left": int(offset_x),
            "top": int(offset_y),
            "width": 0,
            "height": 0,
            "cx": int(offset_x),
            "cy": int(offset_y),
        }
    left = int(round(min(xs))) + int(offset_x)
    top = int(round(min(ys))) + int(offset_y)
    right = int(round(max(xs))) + int(offset_x)
    bottom = int(round(max(ys))) + int(offset_y)
    width = max(0, right - left)
    height = max(0, bottom - top)
    return {
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "cx": left + width // 2,
        "cy": top + height // 2,
    }


def empty_match_outputs() -> dict[str, Any]:
    return {
        "found": False,
        "x": 0,
        "y": 0,
        "left": 0,
        "top": 0,
        "width": 0,
        "height": 0,
        "matched_text": "",
        "count": 0,
    }


def match_outputs_from_box(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return empty_match_outputs()
    left = int(entry.get("left") or 0)
    top = int(entry.get("top") or 0)
    width = int(entry.get("width") or 0)
    height = int(entry.get("height") or 0)
    cx = entry.get("cx")
    cy = entry.get("cy")
    if cx is None:
        cx = left + width // 2
    if cy is None:
        cy = top + height // 2
    return {
        "found": True,
        "x": int(cx),
        "y": int(cy),
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "matched_text": str(entry.get("text") or ""),
        "count": 1,
    }


def match_outputs_from_boxes(entries: list[dict[str, Any]] | None) -> dict[str, Any]:
    """One hit → scalar coords; multiple hits → coordinate arrays."""
    items = [e for e in (entries or []) if isinstance(e, dict)]
    if not items:
        return empty_match_outputs()
    if len(items) == 1:
        return match_outputs_from_box(items[0])

    outs = [match_outputs_from_box(e) for e in items]
    return {
        "found": True,
        "count": len(outs),
        "x": [int(o["x"]) for o in outs],
        "y": [int(o["y"]) for o in outs],
        "left": [int(o["left"]) for o in outs],
        "top": [int(o["top"]) for o in outs],
        "width": [int(o["width"]) for o in outs],
        "height": [int(o["height"]) for o in outs],
        "matched_text": [str(o.get("matched_text") or "") for o in outs],
    }


def find_first_matching_box(
    boxes: list[dict[str, Any]] | None,
    expect: str,
    mode: str,
) -> dict[str, Any] | None:
    """Return the first box whose text matches expect, or None."""
    hits = find_all_matching_boxes(boxes, expect, mode)
    return hits[0] if hits else None


def find_all_matching_boxes(
    boxes: list[dict[str, Any]] | None,
    expect: str,
    mode: str,
) -> list[dict[str, Any]]:
    """Return all boxes whose text matches expect (scan order)."""
    expect = str(expect or "")
    if not expect:
        return []
    out: list[dict[str, Any]] = []
    for item in boxes or []:
        if not isinstance(item, dict):
            continue
        if match_text(str(item.get("text") or ""), expect, mode):
            out.append(item)
    return out


def parse_match_queries(params: dict[str, Any] | None) -> list[str]:
    """Collect match targets from match_text + match_texts (lines or JSON array)."""
    import json

    params = params or {}
    queries: list[str] = []
    single = str(params.get("match_text") or "").strip()
    if single:
        queries.append(single)

    raw = params.get("match_texts")
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = parsed
                else:
                    items = text.splitlines()
            except Exception:
                items = text.splitlines()
        else:
            items = text.splitlines()

    for item in items:
        s = str(item or "").strip()
        if s:
            queries.append(s)

    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def match_all_queries(
    boxes: list[dict[str, Any]] | None,
    queries: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Match each query against boxes; preserve query order. Multi-hits → arrays."""
    matches: list[dict[str, Any]] = []
    for q in queries:
        hits = find_all_matching_boxes(boxes, q, mode)
        entry = match_outputs_from_boxes(hits)
        entry["query"] = q
        matches.append(entry)
    return matches


def _scalar_geom(value: Any, default: int = 0) -> int:
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        try:
            return int(round(float(value[0])))
        except (TypeError, ValueError):
            return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def primary_match_from_list(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level found/x/y: first successful hit (first element if arrays), else empty."""
    for m in matches:
        if m.get("found"):
            matched = m.get("matched_text")
            if isinstance(matched, list):
                matched_text = str(matched[0] if matched else "")
            else:
                matched_text = str(matched or "")
            return {
                "found": True,
                "x": _scalar_geom(m.get("x")),
                "y": _scalar_geom(m.get("y")),
                "left": _scalar_geom(m.get("left")),
                "top": _scalar_geom(m.get("top")),
                "width": _scalar_geom(m.get("width")),
                "height": _scalar_geom(m.get("height")),
                "matched_text": matched_text,
                "count": int(m.get("count") or 1),
            }
    return empty_match_outputs()


def total_match_count(matches: list[dict[str, Any]] | None) -> int:
    """Sum of successful hit counts across all query match entries."""
    total = 0
    for m in matches or []:
        if not isinstance(m, dict) or not m.get("found"):
            continue
        try:
            total += max(0, int(m.get("count") or 0))
        except (TypeError, ValueError):
            total += 1
    return total


_GEOM_KEYS = ("x", "y", "left", "top", "cx", "cy")


def _shift_geom_value(value: Any, *, dx: int, dy: int, key: str) -> Any:
    if value is None:
        return value
    if key in ("x", "left", "cx"):
        delta = dx
    elif key in ("y", "top", "cy"):
        delta = dy
    else:
        return value

    if isinstance(value, list):
        out = []
        for item in value:
            try:
                out.append(int(round(float(item))) - delta)
            except (TypeError, ValueError):
                out.append(item)
        return out
    try:
        return int(round(float(value))) - delta
    except (TypeError, ValueError):
        return value


def shift_coordinate_fields(
    payload: dict[str, Any] | None,
    *,
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict[str, Any]:
    """Subtract region origin from geometry fields (in-place-ish copy)."""
    if not isinstance(payload, dict):
        return {}
    ox, oy = int(origin_x or 0), int(origin_y or 0)
    if ox == 0 and oy == 0:
        return dict(payload)
    out = dict(payload)
    for key in _GEOM_KEYS:
        if key in out:
            out[key] = _shift_geom_value(out[key], dx=ox, dy=oy, key=key)
    return out


def apply_output_coordinate_mode(
    result: dict[str, Any],
    *,
    mode: str,
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict[str, Any]:
    """
    Transform OCR / find-image style results.
    screen_abs: unchanged; region_rel: subtract recognition/search region origin.
    """
    mode_key = str(mode or "screen_abs").strip().lower() or "screen_abs"
    if mode_key != "region_rel":
        return result

    ox, oy = int(origin_x or 0), int(origin_y or 0)
    out = shift_coordinate_fields(result, origin_x=ox, origin_y=oy)

    boxes = out.get("boxes")
    if isinstance(boxes, list):
        out["boxes"] = [
            shift_coordinate_fields(b, origin_x=ox, origin_y=oy) if isinstance(b, dict) else b
            for b in boxes
        ]

    matches = out.get("matches")
    if isinstance(matches, list):
        out["matches"] = [
            shift_coordinate_fields(m, origin_x=ox, origin_y=oy) if isinstance(m, dict) else m
            for m in matches
        ]

    return out
