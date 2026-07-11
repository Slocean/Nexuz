from __future__ import annotations

import re

SCHEMA = {
    "type": "if_text_contains",
    "label": "文字匹配",
    "category": "识别类",
    "inputs": [
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域（推荐：点下方「框选区域」）",
            "default": None,
        },
        {
            "name": "x",
            "type": "number",
            "label": "起点X（无区域时用）",
            "default": 0,
        },
        {
            "name": "y",
            "type": "number",
            "label": "起点Y（无区域时用）",
            "default": 0,
        },
        {
            "name": "width",
            "type": "number",
            "label": "宽度（无区域时用）",
            "default": 320,
        },
        {
            "name": "height",
            "type": "number",
            "label": "高度（无区域时用）",
            "default": 80,
        },
        {"name": "expect_text", "type": "string", "label": "期望文字", "default": ""},
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
        },
        {
            "name": "lang",
            "type": "select",
            "label": "语言",
            "options": ["auto", "ch", "en"],
            "default": "auto",
        },
        {
            "name": "min_confidence",
            "type": "number",
            "label": "最低置信度(0-1)",
            "default": 0.3,
        },
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
        {"name": "actual_text", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from backend.blocks.ocr_recognize import run_ocr

    ocr_out = run_ocr(params)
    actual = str(ocr_out.get("text") or "")
    expect = str(params.get("expect_text") or "")
    mode = str(params.get("match_mode") or "contains")

    if mode == "exact":
        matched = actual.strip() == expect.strip()
    elif mode == "regex":
        try:
            matched = bool(re.search(expect, actual))
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
    else:
        matched = expect in actual if expect else False

    return {"matched": matched, "actual_text": actual}
