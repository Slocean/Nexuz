from __future__ import annotations

from backend.blocks._ocr_match import (
    apply_click_offset,
    empty_match_outputs,
    find_all_matching_boxes,
    match_outputs_from_boxes,
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
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
            "option_labels": {
                "contains": "包含（裁到子串）",
                "exact": "精确（整行或子串）",
                "regex": "正则（裁到命中）",
            },
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
    if not expect:
        return {**empty_match_outputs(), "match_count": 0}
    if not boxes:
        return {**empty_match_outputs(), "match_count": 0}
    hits = find_all_matching_boxes(boxes, expect, mode)
    out = match_outputs_from_boxes(hits)
    out["match_count"] = int(out.get("count") or 0)
    try:
        click_dx = int(round(float(params.get("offset_x") or 0)))
    except (TypeError, ValueError):
        click_dx = 0
    try:
        click_dy = int(round(float(params.get("offset_y") or 0)))
    except (TypeError, ValueError):
        click_dy = 0
    return apply_click_offset(out, offset_x=click_dx, offset_y=click_dy)
