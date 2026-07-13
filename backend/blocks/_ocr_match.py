"""Shared OCR text-match helpers: box AABB, match modes, first-hit coords."""

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
    }


def find_first_matching_box(
    boxes: list[dict[str, Any]] | None,
    expect: str,
    mode: str,
) -> dict[str, Any] | None:
    """Return the first box whose text matches expect, or None."""
    expect = str(expect or "")
    if not expect:
        return None
    for item in boxes or []:
        if not isinstance(item, dict):
            continue
        if match_text(str(item.get("text") or ""), expect, mode):
            return item
    return None


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
    """Match each query against boxes; preserve query order."""
    matches: list[dict[str, Any]] = []
    for q in queries:
        hit = find_first_matching_box(boxes, q, mode)
        entry = match_outputs_from_box(hit)
        entry["query"] = q
        matches.append(entry)
    return matches


def primary_match_from_list(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level found/x/y: first successful hit, else empty."""
    for m in matches:
        if m.get("found"):
            return {
                "found": True,
                "x": int(m.get("x") or 0),
                "y": int(m.get("y") or 0),
                "left": int(m.get("left") or 0),
                "top": int(m.get("top") or 0),
                "width": int(m.get("width") or 0),
                "height": int(m.get("height") or 0),
                "matched_text": str(m.get("matched_text") or ""),
            }
    return empty_match_outputs()
