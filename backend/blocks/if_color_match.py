from __future__ import annotations

from backend.blocks._helpers import color_distance, pixel_color, region_dominant_color

SCHEMA = {
    "type": "if_color_match",
    "label": "颜色匹配",
    "category": "识别类",
    "inputs": [
        {"name": "x", "type": "number", "label": "X", "default": 0},
        {"name": "y", "type": "number", "label": "Y", "default": 0},
        {"name": "region", "type": "rect", "label": "区域(可选)", "default": None},
        {"name": "target_color", "type": "color", "label": "目标颜色", "default": "#FF0000"},
        {"name": "tolerance", "type": "number", "label": "容差", "default": 10},
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
        {"name": "color", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    region = params.get("region")
    if region:
        color = region_dominant_color(region)
    else:
        color = pixel_color(int(params.get("x", 0)), int(params.get("y", 0)))
    target = params.get("target_color") or params.get("color") or "#FF0000"
    tolerance = float(params.get("tolerance", 10) or 0)
    matched = color_distance(color, target) <= tolerance
    return {"matched": matched, "color": color}
