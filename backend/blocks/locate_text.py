from __future__ import annotations

from backend.blocks._ocr_match import (
    empty_match_outputs,
    find_first_matching_box,
    match_outputs_from_box,
)

SCHEMA = {
    "type": "locate_text",
    "label": "文字定位",
    "category": "识别类",
    "inputs": [
        {
            "name": "boxes",
            "type": "string",
            "label": "OCR boxes（绑 {{ocr.boxes}}）",
            "default": "",
            "bindable": True,
        },
        {
            "name": "match_text",
            "type": "string",
            "label": "匹配文字",
            "default": "",
        },
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
            "option_labels": {
                "contains": "包含",
                "exact": "完全相等",
                "regex": "正则",
            },
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
        return empty_match_outputs()
    if not boxes:
        return empty_match_outputs()
    hit = find_first_matching_box(boxes, expect, mode)
    return match_outputs_from_box(hit)
