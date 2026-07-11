from __future__ import annotations

from backend.blocks._helpers import pixel_color, region_dominant_color

SCHEMA = {
    "type": "color_detect",
    "label": "区域取色",
    "category": "识别类",
    "inputs": [
        {"name": "x", "type": "number", "label": "X（单点）", "default": 0},
        {"name": "y", "type": "number", "label": "Y（单点）", "default": 0},
        {"name": "region", "type": "rect", "label": "区域(可选)", "default": None},
    ],
    "outputs": [
        {"name": "color", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    region = params.get("region")
    if region:
        color = region_dominant_color(region)
    else:
        color = pixel_color(int(params.get("x", 0)), int(params.get("y", 0)))
    return {"color": color}
