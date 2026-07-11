from __future__ import annotations

from backend.blocks._helpers import match_template_on_screen, resolve_region_from_params

SCHEMA = {
    "type": "find_image",
    "label": "图像模板匹配",
    "category": "识别类",
    "inputs": [
        {
            "name": "template_image",
            "type": "string",
            "label": "模板图片路径",
            "default": "",
        },
        {
            "name": "search_region",
            "type": "rect",
            "label": "搜索区域(可选)",
            "default": None,
        },
        {
            "name": "threshold",
            "type": "number",
            "label": "相似度阈值(0-1)",
            "default": 0.8,
        },
    ],
    "outputs": [
        {"name": "found", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "score", "type": "number"},
        {"name": "left", "type": "number"},
        {"name": "top", "type": "number"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    template_path = str(params.get("template_image") or "").strip()
    if not template_path:
        raise ValueError("请指定 template_image 模板图片路径")

    search = resolve_region_from_params(params, "search_region", "search_region_norm")
    # Also accept region_norm saved under generic keys when picking into search_region
    if search is None and params.get("region_norm") and params.get("search_region"):
        search = resolve_region_from_params(
            {
                **params,
                "region": params.get("search_region"),
                "region_norm": params.get("region_norm"),
            }
        )

    threshold = float(params.get("threshold") if params.get("threshold") is not None else 0.8)
    return match_template_on_screen(
        template_path,
        search_region=search,
        threshold=threshold,
    )
