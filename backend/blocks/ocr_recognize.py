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
    match_all_queries,
    parse_match_queries,
    primary_match_from_list,
)

SCHEMA = {
    "type": "ocr_recognize",
    "label": "OCR取字",
    "category": "识别类",
    "inputs": [
        {
            "name": "region_mode",
            "type": "select",
            "label": "区域方式",
            "options": ["rect", "xy", "anchor"],
            "default": "rect",
            "option_labels": {
                "rect": "框选区域",
                "xy": "起点+宽高",
                "anchor": "锚点模板",
            },
        },
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域",
            "default": None,
            "show_when": {"region_mode": "rect"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "起点 X",
            "default": 0,
            "show_when": {"region_mode": "xy"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "起点 Y",
            "default": 0,
            "show_when": {"region_mode": "xy"},
        },
        {
            "name": "width",
            "type": "number",
            "label": "宽度",
            "default": 320,
            "show_when": {"region_mode": "xy"},
        },
        {
            "name": "height",
            "type": "number",
            "label": "高度",
            "default": 80,
            "show_when": {"region_mode": "xy"},
        },
        {
            "name": "anchor_template",
            "type": "string",
            "label": "锚点模板",
            "default": "",
            "placeholder": "模板图片路径",
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "anchor_threshold",
            "type": "number",
            "label": "锚点阈值",
            "default": 0.8,
            "placeholder": "0~1",
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "anchor_offset_x",
            "type": "number",
            "label": "锚点偏移 X",
            "default": 0,
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "anchor_offset_y",
            "type": "number",
            "label": "锚点偏移 Y",
            "default": 0,
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "anchor_ocr_width",
            "type": "number",
            "label": "识别宽度",
            "default": 0,
            "placeholder": "0 = 模板宽",
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "anchor_ocr_height",
            "type": "number",
            "label": "识别高度",
            "default": 0,
            "placeholder": "0 = 模板高",
            "show_when": {"region_mode": "anchor"},
        },
        {
            "name": "lang",
            "type": "select",
            "label": "语言",
            "options": ["auto", "ch", "en"],
            "default": "auto",
            "option_labels": {"auto": "自动", "ch": "中文", "en": "英文"},
        },
        {
            "name": "min_confidence",
            "type": "number",
            "label": "最低置信度",
            "default": 0.3,
            "placeholder": "0~1",
        },
        {
            "name": "match_text",
            "type": "string",
            "label": "匹配文字",
            "default": "",
            "placeholder": "要找的字",
        },
        {
            "name": "match_texts",
            "type": "string",
            "label": "匹配多字",
            "default": "",
            "bindable": False,
            "ui": "textarea",
            "placeholder": "匹配值一\n匹配值二\n...",
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
            "label": "保留多边形",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {
                "false": "否",
                "true": "是",
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
        {"name": "matches", "type": "array", "canvas": False},
        {"name": "boxes", "type": "array", "canvas": False},
        {"name": "region", "type": "object", "canvas": False},
        {"name": "anchor", "type": "object", "canvas": False},
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
    Honors region_mode when set: rect | xy | anchor.
    Legacy (no mode): anchor_template → region → x,y,width,height.
    Returns ((x1,y1,x2,y2), anchor_info_or_none).
    """
    mode = str(params.get("region_mode") or "").strip().lower()

    def _from_anchor() -> tuple[tuple[int, int, int, int], dict | None]:
        anchor_tpl = str(params.get("anchor_template") or "").strip()
        if not anchor_tpl:
            raise ValueError("请设置锚点模板（可点「截模板」）")
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

    def _from_xy() -> tuple[tuple[int, int, int, int], dict | None]:
        x = int(params.get("x") or 0)
        y = int(params.get("y") or 0)
        if params.get("point_norm"):
            from backend.blocks._helpers import resolve_point

            x, y = resolve_point(params)
        w = max(8, int(params.get("width") or 320))
        h = max(8, int(params.get("height") or 80))
        x, y = validate_point(x, y)
        return validate_region([x, y, x + w, y + h]), None

    if mode == "anchor":
        return _from_anchor()
    if mode == "xy":
        return _from_xy()
    if mode == "rect":
        resolved = resolve_region_from_params(params)
        if not resolved:
            raise ValueError("请框选识别区域")
        return resolved, None

    # Legacy priority
    if str(params.get("anchor_template") or "").strip():
        return _from_anchor()
    resolved = resolve_region_from_params(params)
    if resolved:
        return resolved, None
    return _from_xy()


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
        "matches": [],
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
    match_mode = str(params.get("match_mode") or "contains")
    queries = parse_match_queries(params)

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

    matches = match_all_queries(boxes, queries, match_mode) if queries else []
    match_out = primary_match_from_list(matches) if matches else empty_match_outputs()

    return {
        **match_out,
        "text": joined,
        "confidence": round(avg, 4),
        "matches": matches,
        "boxes": boxes,
        "region": region,
        "anchor": anchor,
    }


def handler(params, context, **kwargs):
    return run_ocr(params)
