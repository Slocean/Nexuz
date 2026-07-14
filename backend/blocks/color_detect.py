from __future__ import annotations

from backend.blocks._helpers import (
    pixel_color,
    region_dominant_color,
    resolve_point,
    resolve_region_from_params,
)

SCHEMA = {
    "type": "color_detect",
    "label": "取色",
    "category": "识别类",
    "inputs": [
        {
            "name": "sample_mode",
            "type": "select",
            "label": "模式",
            "options": ["point", "region", "multi"],
            "default": "point",
            "option_labels": {
                "point": "单点",
                "region": "区域",
                "multi": "多点",
                # legacy
                "single": "单点",
            },
        },
        {
            "name": "x",
            "type": "number",
            "label": "X",
            "default": 0,
            "show_when": {"sample_mode": ["point", "single"]},
        },
        {
            "name": "y",
            "type": "number",
            "label": "Y",
            "default": 0,
            "show_when": {"sample_mode": ["point", "single"]},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "区域",
            "default": None,
            "show_when": {"sample_mode": "region"},
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


def _normalize_mode(params: dict) -> str:
    mode = str(params.get("sample_mode") or "point").strip() or "point"
    # Legacy "single": prefer region when configured, else point.
    if mode == "single":
        if resolve_region_from_params(params):
            return "region"
        return "point"
    if mode not in ("point", "region", "multi"):
        return "point"
    return mode


def handler(params, context, **kwargs):
    mode = _normalize_mode(params)

    if mode == "region":
        region = resolve_region_from_params(params)
        if not region:
            raise ValueError("区域模式请先框选取色区域")
        color = region_dominant_color(region)
        return {"color": color, "colors": [color], "count": 1}

    if mode == "point":
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
        one = {
            "x": pt.get("x", 0),
            "y": pt.get("y", 0),
            "point_norm": pt.get("point_norm"),
            "coord_space": pt.get("coord_space") or params.get("coord_space"),
        }
        x, y = resolve_point(one)
        colors.append(pixel_color(x, y))

    if not colors:
        raise ValueError("多点模式请至少添加一个取色点")

    return {
        "color": colors[0],
        "colors": colors,
        "count": len(colors),
    }
