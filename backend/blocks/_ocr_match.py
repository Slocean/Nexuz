"""Shared OCR text-match helpers: box AABB, match modes, multi-hit coords."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Common OCR / look-alike confusions (after NFKC). Multi-char variants are below.
_OCR_CONFUSABLE = str.maketrans(
    {
        "〇": "0",
        "○": "0",
        "Ο": "0",
        "о": "0",
        "О": "0",
        "|": "1",
        "丨": "1",
        "—": "-",
        "–": "-",
        "−": "-",
        "＿": "_",
        "註": "注",
        "冊": "册",
    }
)

# Multi-char OCR / locale variants applied after char translate.
_OCR_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("登錄", "登录"),
    ("註冊", "注册"),
    ("註册", "注册"),
    ("注冊", "注册"),
)


def parse_match_options(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse match policy from node params (safe defaults)."""
    params = params or {}

    def _flag(key: str, default: bool = True) -> bool:
        raw = params.get(key)
        if raw is None or raw == "":
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in {"0", "false", "no", "off"}

    try:
        match_index = int(round(float(params.get("match_index") if params.get("match_index") not in (None, "") else 1)))
    except (TypeError, ValueError):
        match_index = 1
    try:
        fuzzy_max = int(round(float(params.get("fuzzy_max_edits") if params.get("fuzzy_max_edits") not in (None, "") else 1)))
    except (TypeError, ValueError):
        fuzzy_max = 1
    fuzzy_max = max(0, min(fuzzy_max, 8))

    order = str(params.get("match_order") or "reading").strip().lower() or "reading"
    if order not in {"reading", "top", "bottom", "left", "right", "nearest"}:
        order = "reading"

    anchor_x = params.get("match_anchor_x", params.get("anchor_x"))
    anchor_y = params.get("match_anchor_y", params.get("anchor_y"))
    try:
        ax = float(anchor_x) if anchor_x not in (None, "") else None
    except (TypeError, ValueError):
        ax = None
    try:
        ay = float(anchor_y) if anchor_y not in (None, "") else None
    except (TypeError, ValueError):
        ay = None

    return {
        "normalize": _flag("text_normalize", True),
        "ignore_space": _flag("ignore_space", False),
        "match_index": match_index,
        "match_order": order,
        "fuzzy_max_edits": fuzzy_max,
        "anchor_x": ax,
        "anchor_y": ay,
    }


def normalize_for_match(
    text: str,
    *,
    normalize: bool = True,
    ignore_space: bool = False,
) -> str:
    """NFKC + confusable folding for robust OCR comparison."""
    s = str(text or "")
    if not normalize and not ignore_space:
        return s
    if normalize:
        s = unicodedata.normalize("NFKC", s)
        s = s.translate(_OCR_CONFUSABLE)
        for src, dst in _OCR_PHRASE_REPLACEMENTS:
            s = s.replace(src, dst)
        s = s.casefold()
    if ignore_space:
        s = re.sub(r"\s+", "", s)
    return s


def _build_norm_index_map(
    text: str,
    *,
    normalize: bool,
    ignore_space: bool,
) -> tuple[str, list[int]]:
    """Return (normalized_text, map norm_i → original_i)."""
    if not normalize and not ignore_space:
        return text, list(range(len(text)))

    # Character-wise: NFKC may expand; map each output char to a source index.
    norm_chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        piece = unicodedata.normalize("NFKC", ch) if normalize else ch
        if normalize:
            piece = piece.translate(_OCR_CONFUSABLE)
            piece = piece.casefold()
        for pch in piece:
            if ignore_space and pch.isspace():
                continue
            norm_chars.append(pch)
            index_map.append(i)
    joined = "".join(norm_chars)
    if normalize:
        # Apply phrase replacements on the joined norm string, remapping indices.
        for src, dst in _OCR_PHRASE_REPLACEMENTS:
            joined, index_map = _replace_with_map(joined, index_map, src, dst)
    return joined, index_map


def _replace_with_map(
    text: str,
    index_map: list[int],
    src: str,
    dst: str,
) -> tuple[str, list[int]]:
    if not src or src not in text:
        return text, index_map
    out_chars: list[str] = []
    out_map: list[int] = []
    i = 0
    n = len(src)
    while i < len(text):
        if text.startswith(src, i):
            # Map replaced span to the first original index of the match.
            base = index_map[i] if i < len(index_map) else (out_map[-1] if out_map else 0)
            for ch in dst:
                out_chars.append(ch)
                out_map.append(base)
            i += n
        else:
            out_chars.append(text[i])
            out_map.append(index_map[i] if i < len(index_map) else i)
            i += 1
    return "".join(out_chars), out_map


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def find_all_match_spans(
    actual: str,
    expect: str,
    mode: str,
    *,
    options: dict[str, Any] | None = None,
) -> list[tuple[int, int]]:
    """Return all [start, end) spans in *original* `actual` that match expect."""
    mode = str(mode or "contains")
    expect = str(expect or "")
    actual = str(actual or "")
    opts = options or {}
    normalize = bool(opts.get("normalize", True))
    ignore_space = bool(opts.get("ignore_space", False))
    fuzzy_max = int(opts.get("fuzzy_max_edits") or 1)

    if mode == "regex":
        if not expect:
            return []
        try:
            flags = re.IGNORECASE if normalize else 0
            pattern = re.compile(expect, flags)
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
        return [(m.start(), m.end()) for m in pattern.finditer(actual)]

    norm_actual, index_map = _build_norm_index_map(
        actual, normalize=normalize, ignore_space=ignore_space
    )
    norm_expect = normalize_for_match(
        expect, normalize=normalize, ignore_space=ignore_space
    )
    if not norm_expect and mode != "exact":
        return []

    def _map_span(ns: int, ne: int) -> tuple[int, int] | None:
        if not index_map:
            return (0, 0) if not actual else None
        if ns >= len(index_map):
            return None
        ne_i = min(ne, len(index_map)) - 1
        if ne_i < ns:
            return None
        start = index_map[ns]
        end = index_map[ne_i] + 1
        return (start, max(start + 1, end))

    if mode == "exact":
        if norm_actual == norm_expect:
            if not actual.strip():
                return [(0, 0)] if not expect.strip() else []
            # Full original string (trim-aware span of stripped content).
            stripped = actual.strip()
            start = actual.find(stripped)
            if start < 0:
                start = 0
            return [(start, start + len(stripped))]
        return []

    spans: list[tuple[int, int]] = []
    if mode == "fuzzy":
        if not norm_expect:
            return []
        n = len(norm_expect)
        if n == 0:
            return []
        # Sliding window over normalized text; also allow ±1 length for edits.
        best: list[tuple[int, int, int]] = []  # (dist, ns, ne)
        max_len = min(len(norm_actual), n + fuzzy_max)
        min_len = max(1, n - fuzzy_max)
        for win_len in range(min_len, max_len + 1):
            if win_len > len(norm_actual):
                break
            for ns in range(0, len(norm_actual) - win_len + 1):
                ne = ns + win_len
                dist = _levenshtein(norm_actual[ns:ne], norm_expect)
                if dist <= fuzzy_max:
                    best.append((dist, ns, ne))
        if not best:
            # Whole-line fuzzy fallback.
            dist = _levenshtein(norm_actual, norm_expect)
            if dist <= max(fuzzy_max, max(1, len(norm_expect) // 4)):
                mapped = _map_span(0, len(index_map))
                return [mapped] if mapped else []
            return []
        best.sort(key=lambda t: (t[0], t[1]))
        # Dedupe overlapping windows: keep best non-overlapping left-to-right.
        taken: list[tuple[int, int]] = []
        used: list[tuple[int, int]] = []
        for dist, ns, ne in best:
            if any(not (ne <= us or ns >= ue) for us, ue in used):
                continue
            mapped = _map_span(ns, ne)
            if mapped:
                taken.append(mapped)
                used.append((ns, ne))
        return taken

    # contains (default): all non-overlapping occurrences in normalized text.
    if not norm_expect:
        return []
    start_at = 0
    while True:
        idx = norm_actual.find(norm_expect, start_at)
        if idx < 0:
            break
        mapped = _map_span(idx, idx + len(norm_expect))
        if mapped:
            spans.append(mapped)
        start_at = idx + max(1, len(norm_expect))
    return spans


def find_match_span(
    actual: str,
    expect: str,
    mode: str,
    *,
    options: dict[str, Any] | None = None,
) -> tuple[int, int] | None:
    """Return the first match span, or None."""
    spans = find_all_match_spans(actual, expect, mode, options=options)
    return spans[0] if spans else None


def match_text(
    actual: str,
    expect: str,
    mode: str,
    *,
    options: dict[str, Any] | None = None,
) -> bool:
    """Match `actual` against `expect` with contains / exact / regex / fuzzy."""
    return find_match_span(actual, expect, mode, options=options) is not None


def _char_weight(ch: str) -> float:
    o = ord(ch)
    if ch.isspace():
        return 0.45
    # CJK / fullwidth / kana / hangul roughly double Latin advance.
    if (
        0x1100 <= o <= 0x11FF
        or 0x2E80 <= o <= 0x9FFF
        or 0xA960 <= o <= 0xA97F
        or 0xAC00 <= o <= 0xD7AF
        or 0xF900 <= o <= 0xFAFF
        or 0xFE30 <= o <= 0xFE4F
        or 0xFF00 <= o <= 0xFFEF
        or 0x3000 <= o <= 0x303F
    ):
        return 2.0
    return 1.0


def _span_ratios(text: str, start: int, end: int) -> tuple[float, float]:
    weights = [_char_weight(c) for c in text] or [1.0]
    total = sum(weights) or 1.0
    start = max(0, min(start, len(weights)))
    end = max(start, min(end, len(weights)))
    left = sum(weights[:start])
    span = sum(weights[start:end]) or weights[min(start, len(weights) - 1)]
    return left / total, (left + span) / total


def refine_box_to_span(
    entry: dict[str, Any],
    start: int,
    end: int,
    *,
    matched_text: str | None = None,
) -> dict[str, Any]:
    """Crop a line-level OCR box to an approximate substring AABB.

    Horizontal LTR by default; vertical boxes (tall) slice along Y.
    Character advances use CJK-aware weights (not pure equal-width).
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

    if start <= 0 and end >= n:
        return out

    left = int(entry.get("left") or 0)
    top = int(entry.get("top") or 0)
    width = int(entry.get("width") or 0)
    height = int(entry.get("height") or 0)
    ratio_l, ratio_r = _span_ratios(text, start, end)
    vertical = height >= max(8, int(width * 1.25)) and n >= 2

    if vertical and height > 0:
        new_top = top + int(round(height * ratio_l))
        new_bottom = top + int(round(height * ratio_r))
        new_height = max(1, new_bottom - new_top)
        new_cy = new_top + new_height // 2
        cx = entry.get("cx")
        if cx is None:
            cx = left + width // 2
        out.update(
            {
                "left": left,
                "top": new_top,
                "width": width,
                "height": new_height,
                "cx": int(cx),
                "cy": new_cy,
            }
        )
    elif width > 0:
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
        ys: list[float] = []
        for pt in poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    xs.append(float(pt[0]))
                    ys.append(float(pt[1]))
                except (TypeError, ValueError):
                    pass
        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            refined_poly: list[list[int]] = []
            for pt in poly:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                try:
                    px, py = float(pt[0]), float(pt[1])
                except (TypeError, ValueError):
                    continue
                if vertical and max_y > min_y:
                    t = (py - min_y) / (max_y - min_y)
                    span_min = min_y + (max_y - min_y) * ratio_l
                    span_max = min_y + (max_y - min_y) * ratio_r
                    ny = span_min + t * (span_max - span_min)
                    refined_poly.append([int(round(px)), int(round(ny))])
                elif max_x > min_x:
                    t = (px - min_x) / (max_x - min_x)
                    span_min = min_x + (max_x - min_x) * ratio_l
                    span_max = min_x + (max_x - min_x) * ratio_r
                    nx = span_min + t * (span_max - span_min)
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


def _hit_center(entry: dict[str, Any]) -> tuple[float, float]:
    cx = entry.get("cx", entry.get("x"))
    cy = entry.get("cy", entry.get("y"))
    try:
        return float(cx), float(cy)
    except (TypeError, ValueError):
        left = float(entry.get("left") or 0)
        top = float(entry.get("top") or 0)
        width = float(entry.get("width") or 0)
        height = float(entry.get("height") or 0)
        return left + width / 2, top + height / 2


def order_match_hits(
    hits: list[dict[str, Any]],
    *,
    order: str = "reading",
    anchor_x: float | None = None,
    anchor_y: float | None = None,
) -> list[dict[str, Any]]:
    """Stable spatial / reading-order sort for multi-hit selection."""
    items = [h for h in hits if isinstance(h, dict)]
    order = str(order or "reading").lower()

    def reading_key(h: dict[str, Any]) -> tuple:
        cx, cy = _hit_center(h)
        return (round(cy / 12), cx, cy)

    if order == "top":
        items.sort(key=lambda h: (_hit_center(h)[1], _hit_center(h)[0]))
    elif order == "bottom":
        items.sort(key=lambda h: (-_hit_center(h)[1], _hit_center(h)[0]))
    elif order == "left":
        items.sort(key=lambda h: (_hit_center(h)[0], _hit_center(h)[1]))
    elif order == "right":
        items.sort(key=lambda h: (-_hit_center(h)[0], _hit_center(h)[1]))
    elif order == "nearest" and anchor_x is not None and anchor_y is not None:
        ax, ay = float(anchor_x), float(anchor_y)

        def dist_key(h: dict[str, Any]) -> tuple:
            cx, cy = _hit_center(h)
            return ((cx - ax) ** 2 + (cy - ay) ** 2, cy, cx)

        items.sort(key=dist_key)
    else:
        items.sort(key=reading_key)
    return items


def pick_match_index(hits: list[dict[str, Any]], match_index: int) -> dict[str, Any] | None:
    """1-based index; 0 or 1 → first; -1 → last."""
    if not hits:
        return None
    try:
        idx = int(match_index)
    except (TypeError, ValueError):
        idx = 1
    if idx < 0:
        return hits[-1]
    if idx == 0:
        idx = 1
    if idx > len(hits):
        return None
    return hits[idx - 1]


def find_first_matching_box(
    boxes: list[dict[str, Any]] | None,
    expect: str,
    mode: str,
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the first box whose text matches expect, or None."""
    hits = find_all_matching_boxes(boxes, expect, mode, options=options)
    return hits[0] if hits else None


def find_all_matching_boxes(
    boxes: list[dict[str, Any]] | None,
    expect: str,
    mode: str,
    *,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return matching boxes; one entry per occurrence (incl. multiple in one line)."""
    expect = str(expect or "")
    mode = str(mode or "contains")
    opts = options or {}
    if mode != "regex" and not expect.strip() and mode != "fuzzy":
        return []
    if mode == "regex" and not expect:
        return []

    out: list[dict[str, Any]] = []
    for item in boxes or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        spans = find_all_match_spans(text, expect, mode, options=opts)
        for start, end in spans:
            span_text = text[start:end]
            out.append(refine_box_to_span(item, start, end, matched_text=span_text))
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
    for key in ("x_all", "y_all", "left_all", "top_all", "cx_all", "cy_all"):
        if key in out:
            base = key[: -len("_all")]
            out[key] = _add(out[key], key=base)
    matches = out.get("matches")
    if isinstance(matches, list):
        shifted_matches = []
        for m in matches:
            if not isinstance(m, dict):
                shifted_matches.append(m)
                continue
            sm = _shift_one(m)
            for key in ("x_all", "y_all", "left_all", "top_all", "cx_all", "cy_all"):
                if key in sm:
                    base = key[: -len("_all")]
                    sm[key] = _add(sm[key], key=base)
            shifted_matches.append(sm)
        out["matches"] = shifted_matches
    return out


def parse_click_offset(params: dict[str, Any] | None) -> tuple[int, int]:
    params = params or {}
    try:
        dx = int(round(float(params.get("offset_x") or 0)))
    except (TypeError, ValueError):
        dx = 0
    try:
        dy = int(round(float(params.get("offset_y") or 0)))
    except (TypeError, ValueError):
        dy = 0
    return dx, dy


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
    *,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Match each query against boxes; preserve query order. Multi-hits → arrays."""
    opts = options or {}
    order = str(opts.get("match_order") or "reading")
    matches: list[dict[str, Any]] = []
    for q in queries:
        hits = find_all_matching_boxes(boxes, q, mode, options=opts)
        hits = order_match_hits(
            hits,
            order=order,
            anchor_x=opts.get("anchor_x"),
            anchor_y=opts.get("anchor_y"),
        )
        if not hits:
            entry = empty_match_outputs()
            entry["query"] = q
            matches.append(entry)
            continue

        all_out = match_outputs_from_boxes(hits)
        picked = pick_match_index(hits, int(opts.get("match_index") or 1))
        if picked is None:
            entry = empty_match_outputs()
            entry["query"] = q
            entry["count"] = len(hits)
            for key in ("x", "y", "left", "top", "width", "height", "matched_text"):
                if isinstance(all_out.get(key), list):
                    entry[f"{key}_all"] = all_out[key]
                elif len(hits) > 1:
                    pass
                else:
                    entry[f"{key}_all"] = [all_out.get(key)]
            matches.append(entry)
            continue

        primary = match_outputs_from_box(picked)
        entry = {
            **primary,
            "query": q,
            "found": True,
            "count": len(hits),
            "primary_index": hits.index(picked) + 1,
        }
        for key in ("x", "y", "left", "top", "width", "height", "matched_text"):
            raw = all_out.get(key)
            if isinstance(raw, list):
                entry[f"{key}_all"] = raw
            elif len(hits) > 1:
                entry[f"{key}_all"] = [
                    match_outputs_from_box(h).get(key) for h in hits
                ]
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
    """Top-level found/x/y: first successful query's selected hit."""
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
                "primary_index": int(m.get("primary_index") or 1),
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


def resolve_match_anchor(
    params: dict[str, Any] | None,
    *,
    region: list | tuple | None = None,
) -> tuple[float | None, float | None]:
    """Anchor for nearest-match: explicit params, else region center."""
    opts = parse_match_options(params)
    ax, ay = opts.get("anchor_x"), opts.get("anchor_y")
    if ax is not None and ay is not None:
        return ax, ay
    if isinstance(region, (list, tuple)) and len(region) >= 4:
        try:
            return (
                (float(region[0]) + float(region[2])) / 2.0,
                (float(region[1]) + float(region[3])) / 2.0,
            )
        except (TypeError, ValueError):
            return None, None
    return None, None


# Shared schema fragments for OCR-like nodes.
MATCH_POLICY_INPUTS: list[dict[str, Any]] = [
    {
        "name": "match_mode",
        "type": "select",
        "label": "匹配模式",
        "options": ["contains", "exact", "regex", "fuzzy"],
        "default": "contains",
        "option_labels": {
            "contains": "包含（裁到子串）",
            "exact": "整行相等",
            "regex": "正则（裁到命中）",
            "fuzzy": "模糊（容错）",
        },
    },
    {
        "name": "text_normalize",
        "type": "select",
        "label": "文本归一化",
        "options": ["true", "false"],
        "default": "true",
        "option_labels": {
            "true": "开（全半角/大小写/常见OCR混淆）",
            "false": "关",
        },
    },
    {
        "name": "ignore_space",
        "type": "select",
        "label": "忽略空白",
        "options": ["false", "true"],
        "default": "false",
        "option_labels": {"false": "否", "true": "是"},
    },
    {
        "name": "match_order",
        "type": "select",
        "label": "多命中排序",
        "options": ["reading", "top", "bottom", "left", "right", "nearest"],
        "default": "reading",
        "option_labels": {
            "reading": "阅读顺序",
            "top": "靠上优先",
            "bottom": "靠下优先",
            "left": "靠左优先",
            "right": "靠右优先",
            "nearest": "距锚点最近",
        },
    },
    {
        "name": "match_index",
        "type": "number",
        "label": "匹配序号",
        "default": 1,
        "placeholder": "从1起；-1=最后一个",
    },
    {
        "name": "fuzzy_max_edits",
        "type": "number",
        "label": "模糊最大编辑距离",
        "default": 1,
        "placeholder": "仅模糊模式",
        "show_when": {"match_mode": ["fuzzy"]},
    },
    {
        "name": "offset_x",
        "type": "number",
        "label": "点击偏移 X",
        "default": 0,
        "placeholder": "相对命中中心，像素",
    },
    {
        "name": "offset_y",
        "type": "number",
        "label": "点击偏移 Y",
        "default": 0,
        "placeholder": "相对命中中心，像素",
    },
]


def match_policy_inputs(*, show_when: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Copy of MATCH_POLICY_INPUTS, optionally with show_when on every field."""
    if not show_when:
        return [dict(item) for item in MATCH_POLICY_INPUTS]
    out: list[dict[str, Any]] = []
    for item in MATCH_POLICY_INPUTS:
        cloned = dict(item)
        existing = cloned.get("show_when")
        if isinstance(existing, dict):
            cloned["show_when"] = {**show_when, **existing}
        else:
            cloned["show_when"] = dict(show_when)
        out.append(cloned)
    return out


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
