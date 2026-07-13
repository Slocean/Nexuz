from __future__ import annotations

from backend.blocks._helpers import (
    pixel_color,
    region_dominant_color,
    resolve_point,
    resolve_region_from_params,
)

SCHEMA = {
    "type": "color_detect",
    "label": "区域取色",
    "category": "识别类",
    "inputs": [
        {"name": "x", "type": "number", "label": "X", "default": 0},
        {"name": "y", "type": "number", "label": "Y", "default": 0},
        {"name": "region", "type": "rect", "label": "区域", "default": None},
    ],
    "outputs": [
        {"name": "color", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    region = resolve_region_from_params(params)
    if region:
        color = region_dominant_color(region)
    else:
        x, y = resolve_point(params)
        color = pixel_color(x, y)
    return {"color": color}
