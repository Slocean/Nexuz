from __future__ import annotations

from backend.blocks._helpers import grab_region, validate_point, validate_region

SCHEMA = {
    "type": "ocr_recognize",
    "label": "OCR 文字识别",
    "category": "识别类",
    "inputs": [
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域（推荐：点下方「框选区域」）",
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
    ],
    "outputs": [
        {"name": "text", "type": "string"},
        {"name": "confidence", "type": "number"},
        {"name": "boxes", "type": "any"},
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


def resolve_ocr_region(params: dict) -> tuple[int, int, int, int]:
    """Prefer explicit region; otherwise build box from x,y,width,height."""
    region = params.get("region")
    if region:
        return validate_region(region)

    x = int(params.get("x") or 0)
    y = int(params.get("y") or 0)
    w = max(8, int(params.get("width") or 320))
    h = max(8, int(params.get("height") or 80))
    validate_point(x, y)
    return validate_region([x, y, x + w, y + h])


def run_ocr(params: dict) -> dict:
    x1, y1, x2, y2 = resolve_ocr_region(params)
    img = grab_region(x1, y1, x2, y2)

    engine = _get_ocr()
    import numpy as np

    arr = np.array(img)
    result, _elapsed = engine(arr)
    if not result:
        return {"text": "", "confidence": 0.0, "boxes": []}

    min_conf = float(params.get("min_confidence") if params.get("min_confidence") is not None else 0.3)
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
        boxes.append({"text": text, "confidence": score, "box": box})

    joined = "\n".join(texts)
    avg = sum(scores) / len(scores) if scores else 0.0
    return {"text": joined, "confidence": round(avg, 4), "boxes": boxes}


def handler(params, context, **kwargs):
    return run_ocr(params)
