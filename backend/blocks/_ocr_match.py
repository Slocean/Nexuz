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
