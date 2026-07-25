"""Shared OCR text-match helpers: box AABB, match modes, multi-hit coords."""

from __future__ import annotations

import re
from typing import Any


def find_match_span(actual: str, expect: str, mode: str) -> tuple[int, int] | None:
    """Return [start, end) character indices of the match inside `actual`.

    OCR engines usually return line-level boxes (e.g. 「没有账号？注册」).
    Callers use this span to crop geometry to the matched substring.
    """
    mode = str(mode or "contains")
    expect = str(expect or "")
    actual = str(actual or "")
    if mode == "exact":
        a = actual.strip()
        e = expect.strip()
        if not e:
            return None
        if a == e:
            # Prefer the stripped content span within the raw string.
            start = actual.find(a)
            if start < 0:
                start = 0
            return (start, start + len(a))
        # Line-level OCR: allow exact needle as a contiguous substring.
        idx = actual.find(e)
        if idx >= 0:
            return (idx, idx + len(e))
        return None
    if mode == "regex":
        try:
            m = re.search(expect, actual)
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
        if not m:
            return None
        return (m.start(), m.end())
    if not expect:
        return None
    idx = actual.find(expect)
    if idx < 0:
        return None
    return (idx, idx + len(expect))


def match_text(actual: str, expect: str, mode: str) -> bool:
    """Match `actual` against `expect` with contains / exact / regex."""
    return find_match_span(actual, expect, mode) is not None


def refine_box_to_span(
    entry: dict[str, Any],
    start: int,
    end: int,
    *,
    matched_text: str | None = None,
) -> dict[str, Any]:
    """Crop a line-level OCR box to an approximate substring AABB (LTR).

    Character widths are estimated proportionally across the box width.
    """
    text = str(entry.get("text") or "")
    n = len(text)
    out = dict(entry)
    if n <= 0:
        if matched_text is not None:
            out["text"] = matched_text
        return out

    start = max(0, min(int(start), n))
    end = max(start, min(int(end), n))
    span_text = text[start:end] if matched_text is None else str(matched_text)
    out["text"] = span_text
    out["match_span"] = [start, end]

    # Full-line hit: keep original geometry (center of whole box).
    if start <= 0 and end >= n:
        return out

    left = int(entry.get("left") or 0)
    top = int(entry.get("top") or 0)
    width = int(entry.get("width") or 0)
    height = int(entry.get("height") or 0)
    if width <= 0:
        return out

    ratio_l = start / n
    ratio_r = end / n
    new_left = left + int(round(width * ratio_l))
    new_right = left + int(round(width * ratio_r))
    new_width = max(1, new_right - new_left)
    new_cx = new_left + new_width // 2
    cy = entry.get("cy")
    if cy is None:
        cy = top + height // 2
    out.update(
        {
            "left": new_left,
            "top": top,
            "width": new_width,
            "height": height,
            "cx": new_cx,
            "cy": int(cy),
        }
    )

    poly = entry.get("box")
    if isinstance(poly, list) and poly:
        xs: list[float] = []
        for pt in poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    xs.append(float(pt[0]))
                except (TypeError, ValueError):
                    pass
        if xs:
            min_x, max_x = min(xs), max(xs)
            span_min = min_x + (max_x - min_x) * ratio_l
            span_max = min_x + (max_x - min_x) * ratio_r
            refined_poly: list[list[int]] = []
            for pt in poly:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                try:
                    px, py = float(pt[0]), float(pt[1])
                except (TypeError, ValueError):
                    continue
                # Map x into the span band; keep relative position within old width.
                if max_x > min_x:
                    t = (px - min_x) / (max_x - min_x)
                    nx = span_min + t * (span_max - span_min)
                else:
                    nx = span_min
                refined_poly.append([int(round(nx)), int(round(py))])
            if refined_poly:
                out["box"] = refined_poly
    return out


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
    """Return matching boxes; crop geometry to the matched substring when possible."""
    expect = str(expect or "")
    mode = str(mode or "contains")
    # Regex may be empty? treat like others — require non-empty expect for contains/exact.
    if mode != "regex" and not expect:
        return []
    if mode == "regex" and not expect:
        return []
    out: list[dict[str, Any]] = []
    for item in boxes or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        span = find_match_span(text, expect, mode)
        if span is None:
            continue
        start, end = span
        span_text = text[start:end]
        out.append(
            refine_box_to_span(item, start, end, matched_text=span_text)
        )
    return out


def apply_click_offset(
    payload: dict[str, Any] | None,
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> dict[str, Any]:
    """Add click offsets to geometry fields (top-level + matches). Does not alter raw boxes."""
    if not isinstance(payload, dict):
        return {}
    dx, dy = int(offset_x or 0), int(offset_y or 0)
    if dx == 0 and dy == 0:
        return dict(payload)

    def _add(value: Any, *, key: str) -> Any:
        if value is None:
            return value
        if key in ("x", "left", "cx"):
            delta = dx
        elif key in ("y", "top", "cy"):
            delta = dy
        else:
            return value
        if isinstance(value, list):
            out_list = []
            for item in value:
                try:
                    out_list.append(int(round(float(item))) + delta)
                except (TypeError, ValueError):
                    out_list.append(item)
            return out_list
        try:
            return int(round(float(value))) + delta
        except (TypeError, ValueError):
            return value

    def _shift_one(entry: dict[str, Any]) -> dict[str, Any]:
        shifted = dict(entry)
        for key in _GEOM_KEYS:
            if key in shifted:
                shifted[key] = _add(shifted[key], key=key)
        return shifted

    out = _shift_one(payload)
    matches = out.get("matches")
    if isinstance(matches, list):
        out["matches"] = [
            _shift_one(m) if isinstance(m, dict) else m for m in matches
        ]
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


def _point_xy(payload: dict[str, Any]) -> tuple[int, int] | None:
    """Prefer x/y; boxes often only have cx/cy."""
    raw_x = payload.get("x", payload.get("cx"))
    raw_y = payload.get("y", payload.get("cy"))
    if isinstance(raw_x, (list, tuple)) or isinstance(raw_y, (list, tuple)):
        return None
    try:
        if raw_x is None or raw_y is None or raw_x == "" or raw_y == "":
            return None
        return int(round(float(raw_x))), int(round(float(raw_y)))
    except (TypeError, ValueError):
        return None


def _attach_window_targets(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep screen-abs geometry; attach window_target / list from live window under point.

    OCR does not detect windows itself — we bind the top-level HWND under the
    click point (WindowFromPoint). Skip empty / (0,0) results so we don't latch
    onto whatever sits at the desktop origin (often the IDE).
    """
    if not isinstance(payload, dict):
        return {}
    out = dict(payload)
    if out.get("found") is False:
        return out
    try:
        from backend.core.window_coords import capture_window_target, retarget_window_point
    except Exception:
        return out

    raw_x = out.get("x", out.get("cx"))
    raw_y = out.get("y", out.get("cy"))
    if isinstance(raw_x, (list, tuple)) and isinstance(raw_y, (list, tuple)):
        targets: list[Any] = []
        base = None
        for xi, yi in zip(raw_x, raw_y):
            try:
                px, py = int(round(float(xi))), int(round(float(yi)))
            except (TypeError, ValueError):
                targets.append(None)
                continue
            if px == 0 and py == 0:
                targets.append(None)
                continue
            try:
                if base is None:
                    base = capture_window_target(px, py)
                    targets.append(base)
                elif isinstance(base, dict):
                    targets.append(retarget_window_point(base, px, py))
                else:
                    targets.append(capture_window_target(px, py))
            except Exception:
                targets.append(None)
        if any(isinstance(t, dict) for t in targets):
            out["window_target"] = targets
        return out

    pt = _point_xy(out)
    if pt is None or (pt[0] == 0 and pt[1] == 0):
        return out
    try:
        target = capture_window_target(pt[0], pt[1])
    except Exception:
        target = None
    if isinstance(target, dict):
        out["window_target"] = target
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

    - screen_abs: unchanged desktop pixels
    - region_rel: subtract recognition/search region origin
    - window_client: keep screen pixels, attach window_target (point_norm) for click replay
    """
    mode_key = str(mode or "screen_abs").strip().lower() or "screen_abs"
    if mode_key == "region_rel":
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
        out["coordinate_mode"] = "region_rel"
        return out

    if mode_key != "window_client":
        out = dict(result) if isinstance(result, dict) else {}
        out["coordinate_mode"] = "screen_abs"
        return out

    out = dict(result) if isinstance(result, dict) else {}
    # Prefer the window under the OCR region center (stable). OCR does not
    # "see" windows — we bind HWND after the fact via Win32.
    base_wt = None
    region = out.get("region")
    if isinstance(region, (list, tuple)) and len(region) >= 4:
        try:
            from backend.core.window_coords import capture_window_target, retarget_window_point

            rcx = (int(region[0]) + int(region[2])) // 2
            rcy = (int(region[1]) + int(region[3])) // 2
            base_wt = capture_window_target(rcx, rcy)
        except Exception:
            base_wt = None

    def _bind(payload: dict[str, Any]) -> dict[str, Any]:
        attached = _attach_window_targets(payload)
        if not isinstance(base_wt, dict):
            return attached
        pt = _point_xy(attached)
        if pt is None:
            return attached
        try:
            from backend.core.window_coords import retarget_window_point

            attached["window_target"] = retarget_window_point(base_wt, pt[0], pt[1])
        except Exception:
            pass
        return attached

    out = _bind(out)
    boxes = out.get("boxes")
    if isinstance(boxes, list):
        out["boxes"] = [_bind(b) if isinstance(b, dict) else b for b in boxes]
    matches = out.get("matches")
    if isinstance(matches, list):
        out["matches"] = [_bind(m) if isinstance(m, dict) else m for m in matches]
    out["coordinate_mode"] = "window_client"
    return out
