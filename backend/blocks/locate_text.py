from __future__ import annotations

from backend.blocks._ocr_match import (
    MATCH_POLICY_INPUTS,
    apply_click_offset,
    empty_match_outputs,
    find_all_matching_boxes,
    match_outputs_from_box,
    match_outputs_from_boxes,
    order_match_hits,
    parse_click_offset,
    parse_match_options,
    pick_match_index,
)

SCHEMA = {
    "type": "locate_text",
    "label": "文字定位",
    "category": "识别类",
    "inputs": [
        {
            "name": "boxes",
            "type": "string",
            "label": "boxes",
            "default": "",
            "bindable": True,
            "placeholder": "{{ocr节点.boxes}}",
        },
        {
            "name": "match_text",
            "type": "string",
            "label": "匹配文字",
            "default": "",
            "placeholder": "要找的字",
        },
        *MATCH_POLICY_INPUTS,
    ],
    "outputs": [
        {"name": "found", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "left", "type": "number"},
        {"name": "top", "type": "number"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "matched_text", "type": "string"},
        {"name": "match_count", "type": "number"},
        {"name": "primary_index", "type": "number"},
    ],
}


def _coerce_boxes(raw) -> list:
    if isinstance(raw, list):
        return [b for b in raw if isinstance(b, dict)]
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [b for b in parsed if isinstance(b, dict)]
        except Exception:
            return []
    return []


def handler(params, context, **kwargs):
    boxes = _coerce_boxes(params.get("boxes"))
    expect = str(params.get("match_text") or "").strip()
    mode = str(params.get("match_mode") or "contains")
    opts = parse_match_options(params)
    if not expect:
        return {**empty_match_outputs(), "match_count": 0, "primary_index": 0}
    if not boxes:
        return {**empty_match_outputs(), "match_count": 0, "primary_index": 0}
    hits = find_all_matching_boxes(boxes, expect, mode, options=opts)
    hits = order_match_hits(
        hits,
        order=str(opts.get("match_order") or "reading"),
        anchor_x=opts.get("anchor_x"),
        anchor_y=opts.get("anchor_y"),
    )
    if not hits:
        return {**empty_match_outputs(), "match_count": 0, "primary_index": 0}
    picked = pick_match_index(hits, int(opts.get("match_index") or 1))
    if picked is None:
        all_out = match_outputs_from_boxes(hits)
        return {
            **empty_match_outputs(),
            "match_count": len(hits),
            "primary_index": 0,
            "x_all": all_out.get("x") if isinstance(all_out.get("x"), list) else [all_out.get("x")],
            "y_all": all_out.get("y") if isinstance(all_out.get("y"), list) else [all_out.get("y")],
        }
    out = match_outputs_from_box(picked)
    out["match_count"] = len(hits)
    out["primary_index"] = hits.index(picked) + 1
    if len(hits) > 1:
        all_out = match_outputs_from_boxes(hits)
        for key in ("x", "y", "left", "top", "width", "height", "matched_text"):
            raw = all_out.get(key)
            out[f"{key}_all"] = raw if isinstance(raw, list) else [raw]
    click_dx, click_dy = parse_click_offset(params)
    return apply_click_offset(out, offset_x=click_dx, offset_y=click_dy)
