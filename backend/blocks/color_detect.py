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
        {
            "name": "sample_mode",
            "type": "select",
            "label": "模式",
            "options": ["single", "multi"],
            "default": "single",
            "option_labels": {"single": "单点", "multi": "多点"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "X",
            "default": 0,
            "show_when": {"sample_mode": "single"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "Y",
            "default": 0,
            "show_when": {"sample_mode": "single"},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "区域",
            "default": None,
            "show_when": {"sample_mode": "single"},
        },
        {
            "name": "points",
            "type": "point_list",
            "label": "取色点",
            "default": [],
            "bindable": False,
            "show_when": {"sample_mode": "multi"},
        },
    ],
    "outputs": [
        {"name": "color", "type": "string"},
        {"name": "colors", "type": "any", "canvas": False},
        {"name": "count", "type": "number"},
    ],
}


def _as_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def handler(params, context, **kwargs):
    mode = str(params.get("sample_mode") or "single").strip() or "single"

    if mode != "multi":
        region = resolve_region_from_params(params)
        if region:
            color = region_dominant_color(region)
        else:
            x, y = resolve_point(params)
            color = pixel_color(x, y)
        return {"color": color, "colors": [color], "count": 1}

    raw_points = params.get("points") or []
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("多点模式请至少添加一个取色点")

    colors: list[str] = []
    for pt in raw_points:
        if not isinstance(pt, dict):
            continue
        x = _as_int(pt.get("x"), 0)
        y = _as_int(pt.get("y"), 0)
        colors.append(pixel_color(x, y))

    if not colors:
        raise ValueError("多点模式请至少添加一个取色点")

    return {
        "color": colors[0],
        "colors": colors,
        "count": len(colors),
    }
