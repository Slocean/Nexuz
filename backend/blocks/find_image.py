from __future__ import annotations

from pathlib import Path

from backend.blocks._helpers import grab_region, validate_region

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
    ],
}


def handler(params, context, **kwargs):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "未安装找图依赖，请执行: pip install opencv-python-headless"
        ) from exc

    template_path = str(params.get("template_image") or "").strip()
    if not template_path:
        raise ValueError("请指定 template_image 模板图片路径")
    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"模板图片不存在: {template_path}")

    tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if tpl is None:
        raise ValueError(f"无法读取模板图片: {template_path}")

    search_region = params.get("search_region")
    if search_region:
        x1, y1, x2, y2 = validate_region(search_region)
        hay_img = grab_region(x1, y1, x2, y2)
        origin_x, origin_y = x1, y1
    else:
        # full primary monitor via mss through a large grab — use screen size
        from backend.core.dpi import screen_size_logical

        w, h = screen_size_logical()
        hay_img = grab_region(0, 0, w, h)
        origin_x, origin_y = 0, 0

    hay = cv2.cvtColor(np.array(hay_img), cv2.COLOR_RGB2BGR)
    if hay.shape[0] < tpl.shape[0] or hay.shape[1] < tpl.shape[1]:
        return {"found": False, "x": 0, "y": 0, "score": 0.0}

    res = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
    threshold = float(params.get("threshold") if params.get("threshold") is not None else 0.8)
    found = float(max_val) >= threshold
    cx = int(origin_x + max_loc[0] + tpl.shape[1] / 2)
    cy = int(origin_y + max_loc[1] + tpl.shape[0] / 2)
    return {
        "found": found,
        "x": cx if found else 0,
        "y": cy if found else 0,
        "score": round(float(max_val), 4),
    }
