from __future__ import annotations

from backend.blocks._helpers import (
    grab_region,
    match_template_on_screen,
    resolve_region_from_params,
    validate_point,
    validate_region,
)
from backend.blocks._ocr_match import (
    aabb_from_polygon,
    empty_match_outputs,
    find_first_matching_box,
    match_outputs_from_box,
)

SCHEMA = {
    "type": "ocr_recognize",
    "label": "OCR 文字识别",
    "category": "识别类",
    "inputs": [
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域（推荐：拖拽框选）",
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
        {
            "name": "anchor_template",
            "type": "string",
            "label": "锚点模板路径(可选，先找图再识别)",
            "default": "",
        },
        {
            "name": "anchor_threshold",
            "type": "number",
            "label": "锚点相似度阈值",
            "default": 0.8,
        },
        {
            "name": "anchor_offset_x",
            "type": "number",
            "label": "相对锚点左上角偏移X",
            "default": 0,
        },
        {
            "name": "anchor_offset_y",
            "type": "number",
            "label": "相对锚点左上角偏移Y",
            "default": 0,
        },
        {
            "name": "anchor_ocr_width",
            "type": "number",
            "label": "锚点模式下识别宽度(0=用模板宽)",
            "default": 0,
        },
        {
            "name": "anchor_ocr_height",
            "type": "number",
            "label": "锚点模式下识别高度(0=用模板高)",
            "default": 0,
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
        {
            "name": "match_text",
            "type": "string",
            "label": "匹配文字(可选，填则输出该字中心坐标供点击)",
            "default": "",
        },
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
            "option_labels": {
                "contains": "包含",
                "exact": "完全相等",
                "regex": "正则",
            },
        },
        {
            "name": "include_box_geometry",
            "type": "select",
            "label": "保留文字框多边形",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {
                "false": "否（默认；仍保留中心/包围盒）",
                "true": "是（boxes 另含多边形）",
            },
        },
    ],
    "outputs": [
        {"name": "found", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "left", "type": "number"},
        {"name": "top", "type": "number"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "matched_text", "type": "string"},
        {"name": "text", "type": "string"},
        {"name": "confidence", "type": "number"},
        {"name": "boxes", "type": "any"},
        {"name": "region", "type": "any"},
        {"name": "anchor", "type": "any"},
    ],
}

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "未安装 OCR 依赖，请执行: pip install rapidocr-onnxruntime"
            ) from exc
        _ocr_engine = RapidOCR()
    return _ocr_engine


def resolve_ocr_region(params: dict) -> tuple[tuple[int, int, int, int], dict | None]:
    """
    Resolve OCR box.
    Priority: anchor_template → region/region_norm → x,y,width,height.
    Returns ((x1,y1,x2,y2), anchor_info_or_none).
    """
    anchor_tpl = str(params.get("anchor_template") or "").strip()
    if anchor_tpl:
        search = resolve_region_from_params(params, "search_region", "search_region_norm")
        match = match_template_on_screen(
            anchor_tpl,
            search_region=search,
            threshold=float(
                params.get("anchor_threshold")
                if params.get("anchor_threshold") is not None
                else 0.8
            ),
        )
        if not match.get("found"):
            raise ValueError(
                f"未找到锚点模板 (score={match.get('score', 0)})，无法定位 OCR 区域"
            )
        ox = int(params.get("anchor_offset_x") or 0)
        oy = int(params.get("anchor_offset_y") or 0)
        ow = int(params.get("anchor_ocr_width") or 0)
        oh = int(params.get("anchor_ocr_height") or 0)
        if ow <= 0:
            ow = int(match["width"]) or 120
        if oh <= 0:
            oh = int(match["height"]) or 40
        x1 = int(match["left"]) + ox
        y1 = int(match["top"]) + oy
        region = validate_region([x1, y1, x1 + ow, y1 + oh])
        return region, match

    resolved = resolve_region_from_params(params)
    if resolved:
        return resolved, None

    x = int(params.get("x") or 0)
    y = int(params.get("y") or 0)
    # Prefer point_norm for origin if present
    if params.get("point_norm"):
        from backend.blocks._helpers import resolve_point

        x, y = resolve_point(params)
    w = max(8, int(params.get("width") or 320))
    h = max(8, int(params.get("height") or 80))
    validate_point(x, y)
    return validate_region([x, y, x + w, y + h]), None


def _compact_box(box) -> list:
    """Round polygon points to ints to cut float payload size."""
    out = []
    try:
        for pt in box or []:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                out.append([int(round(float(pt[0]))), int(round(float(pt[1])))])
    except Exception:
        return []
    return out


def _empty_ocr_result(
    region: list[int],
    anchor: dict | None,
) -> dict:
    return {
        **empty_match_outputs(),
        "text": "",
        "confidence": 0.0,
        "boxes": [],
        "region": region,
        "anchor": anchor,
    }


def run_ocr(params: dict) -> dict:
    (x1, y1, x2, y2), anchor = resolve_ocr_region(params)
    region = [x1, y1, x2, y2]
    img = grab_region(x1, y1, x2, y2)

    engine = _get_ocr()
    import numpy as np

    arr = np.asarray(img)
    try:
        result, _elapsed = engine(arr)
    finally:
        # Release screenshot buffer promptly; RapidOCR may retain its own copy.
        del arr
        try:
            img.close()
        except Exception:
            pass

    if not result:
        return _empty_ocr_result(region, anchor)

    min_conf = float(
        params.get("min_confidence") if params.get("min_confidence") is not None else 0.3
    )
    include_geometry = str(params.get("include_box_geometry", "false")).lower() == "true"
    match_expect = str(params.get("match_text") or "").strip()
    match_mode = str(params.get("match_mode") or "contains")

    texts: list[str] = []
    scores: list[float] = []
    boxes: list[dict] = []
    for item in result:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], item[1], float(item[2])
        if score < min_conf:
            continue
        texts.append(str(text))
        scores.append(score)
        poly = _compact_box(box)
        geom = aabb_from_polygon(poly, offset_x=x1, offset_y=y1)
        entry: dict = {
            "text": text,
            "confidence": round(score, 4),
            "left": geom["left"],
            "top": geom["top"],
            "width": geom["width"],
            "height": geom["height"],
            "cx": geom["cx"],
            "cy": geom["cy"],
        }
        if include_geometry:
            entry["box"] = poly
        boxes.append(entry)
        if len(boxes) >= 80:
            break

    joined = "\n".join(texts)
    avg = sum(scores) / len(scores) if scores else 0.0

    hit = find_first_matching_box(boxes, match_expect, match_mode) if match_expect else None
    match_out = match_outputs_from_box(hit)

    return {
        **match_out,
        "text": joined,
        "confidence": round(avg, 4),
        "boxes": boxes,
        "region": region,
        "anchor": anchor,
    }


def handler(params, context, **kwargs):
    return run_ocr(params)
