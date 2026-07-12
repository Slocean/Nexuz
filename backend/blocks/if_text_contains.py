from __future__ import annotations

import re

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
                "value": "使用已有文本（上游/变量）",
            },
        },
        {
            "name": "actual_text",
            "type": "string",
            "label": "实际文本",
            "default": "",
            "show_when": {"source_mode": "value"},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域（推荐：拖拽框选）",
            "default": None,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "起点X（无区域时用）",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "起点Y（无区域时用）",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "width",
            "type": "number",
            "label": "宽度（无区域时用）",
            "default": 320,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "height",
            "type": "number",
            "label": "高度（无区域时用）",
            "default": 80,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_template",
            "type": "string",
            "label": "锚点模板路径(可选，先找图再识别)",
            "default": "",
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_threshold",
            "type": "number",
            "label": "锚点相似度阈值",
            "default": 0.8,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_offset_x",
            "type": "number",
            "label": "相对锚点左上角偏移X",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_offset_y",
            "type": "number",
            "label": "相对锚点左上角偏移Y",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_ocr_width",
            "type": "number",
            "label": "锚点模式下识别宽度(0=用模板宽)",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "anchor_ocr_height",
            "type": "number",
            "label": "锚点模式下识别高度(0=用模板高)",
            "default": 0,
            "show_when": {"source_mode": "capture"},
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
            "label": "最低置信度(0-1)",
            "default": 0.3,
            "show_when": {"source_mode": "capture"},
        },
        {"name": "expect_text", "type": "string", "label": "期望文字", "default": ""},
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
    ],
}


def _match_text(actual: str, expect: str, mode: str) -> bool:
    if mode == "exact":
        return actual.strip() == expect.strip()
    if mode == "regex":
        try:
            return bool(re.search(expect, actual))
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
    return expect in actual if expect else False


def handler(params, context, **kwargs):
    mode = str(params.get("match_mode") or "contains")
    expect = str(params.get("expect_text") or "")
    source = str(params.get("source_mode") or "capture").strip() or "capture"

    if source == "value":
        actual = str(params.get("actual_text") or "")
    else:
        from backend.blocks.ocr_recognize import run_ocr

        ocr_out = run_ocr(params)
        actual = str(ocr_out.get("text") or "")

    matched = _match_text(actual, expect, mode)
    return {"matched": matched, "actual_text": actual}
