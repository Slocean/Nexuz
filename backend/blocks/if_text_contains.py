from __future__ import annotations

from backend.blocks._ocr_match import empty_match_outputs, match_text

SCHEMA = {
    "type": "if_text_contains",
    "label": "文字匹配",
    "category": "识别类",
    "inputs": [
        {
            "name": "source_mode",
            "type": "select",
            "label": "数据来源",
            "options": ["capture", "value"],
            "default": "capture",
            "option_labels": {
                "capture": "现场 OCR",
                "value": "上游文本",
            },
        },
        {
            "name": "actual_text",
            "type": "string",
            "label": "实际文本",
            "default": "",
            "show_when": {"source_mode": "value"},
            "placeholder": "要比对的文本",
        },
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域",
            "default": None,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "起点 X",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "起点 Y",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "width",
            "type": "number",
            "label": "宽度",
            "default": 320,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "height",
            "type": "number",
            "label": "高度",
            "default": 80,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_template",
            "type": "string",
            "label": "锚点模板",
            "default": "",
            "show_when": {"source_mode": "capture"},
            "placeholder": "模板图片路径",
        },
        {
            "name": "anchor_threshold",
            "type": "number",
            "label": "锚点阈值",
            "default": 0.8,
            "show_when": {"source_mode": "capture"},
            "placeholder": "0~1",
        },
        {
            "name": "anchor_offset_x",
            "type": "number",
            "label": "锚点偏移 X",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_offset_y",
            "type": "number",
            "label": "锚点偏移 Y",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_ocr_width",
            "type": "number",
            "label": "识别宽度",
            "default": 0,
            "show_when": {"source_mode": "capture"},
            "placeholder": "0 = 模板宽",
        },
        {
            "name": "anchor_ocr_height",
            "type": "number",
            "label": "识别高度",
            "default": 0,
            "show_when": {"source_mode": "capture"},
            "placeholder": "0 = 模板高",
        },
        {
            "name": "lang",
            "type": "select",
            "label": "语言",
            "options": ["auto", "ch", "en"],
            "default": "auto",
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "min_confidence",
            "type": "number",
            "label": "最低置信度",
            "default": 0.3,
            "show_when": {"source_mode": "capture"},
            "placeholder": "0~1",
        },
        {
            "name": "expect_text",
            "type": "string",
            "label": "期望文字",
            "default": "",
            "placeholder": "要匹配的字",
        },
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
        },
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
        {"name": "actual_text", "type": "string"},
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


def handler(params, context, **kwargs):
    mode = str(params.get("match_mode") or "contains")
    expect = str(params.get("expect_text") or "")
    source = str(params.get("source_mode") or "capture").strip() or "capture"

    if source == "value":
        actual = str(params.get("actual_text") or "")
        matched = match_text(actual, expect, mode)
        return {
            "matched": matched,
            "actual_text": actual,
            **empty_match_outputs(),
            "matched_text": actual if matched else "",
            "found": matched,
        }

    from backend.blocks.ocr_recognize import run_ocr

    ocr_out = run_ocr({**params, "match_text": expect, "match_mode": mode})
    actual = str(ocr_out.get("text") or "")
    # Branch on full joined text (existing semantics); coords from box-level hit.
    matched = match_text(actual, expect, mode)
    return {
        "matched": matched,
        "actual_text": actual,
        "found": bool(ocr_out.get("found")),
        "x": int(ocr_out.get("x") or 0),
        "y": int(ocr_out.get("y") or 0),
        "left": int(ocr_out.get("left") or 0),
        "top": int(ocr_out.get("top") or 0),
        "width": int(ocr_out.get("width") or 0),
        "height": int(ocr_out.get("height") or 0),
        "matched_text": str(ocr_out.get("matched_text") or ""),
    }
