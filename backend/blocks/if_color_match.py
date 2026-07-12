from __future__ import annotations

from backend.blocks._helpers import (
    color_distance,
    pixel_color,
    region_dominant_color,
    resolve_point,
    resolve_region_from_params,
)

SCHEMA = {
    "type": "if_color_match",
    "label": "颜色匹配",
    "category": "识别类",
    "inputs": [
        {
            "name": "source_mode",
            "type": "select",
            "label": "数据来源",
            "options": ["capture", "value"],
            "default": "capture",
            "option_labels": {
                "capture": "现场取色",
                "value": "使用已有颜色（上游/变量）",
            },
        },
        {
            "name": "actual_color",
            "type": "string",
            "label": "实际颜色",
            "default": "",
            "show_when": {"source_mode": "value"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "X",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "Y",
            "default": 0,
            "show_when": {"source_mode": "capture"},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "区域(可选)",
            "default": None,
            "show_when": {"source_mode": "capture"},
        },
        {"name": "target_color", "type": "color", "label": "目标颜色", "default": "#FF0000"},
        {"name": "tolerance", "type": "number", "label": "容差", "default": 10},
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
        {"name": "color", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    source = str(params.get("source_mode") or "capture").strip() or "capture"
    target = params.get("target_color") or params.get("color") or "#FF0000"
    tolerance = float(params.get("tolerance", 10) or 0)

    if source == "value":
        color = str(params.get("actual_color") or params.get("color") or "").strip()
        if not color:
            raise ValueError("请绑定或填写实际颜色（如 {{取色节点.color}}）")
    else:
        region = resolve_region_from_params(params)
        if region:
            color = region_dominant_color(region)
        else:
            x, y = resolve_point(params)
            color = pixel_color(x, y)

    matched = color_distance(color, target) <= tolerance
    return {"matched": matched, "color": color}
