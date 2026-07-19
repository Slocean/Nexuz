from __future__ import annotations

import gc
import threading
import time
from pathlib import Path

from backend.blocks._helpers import (
    grab_region,
    match_template_on_screen,
    resolve_region_from_params,
    validate_point,
    validate_region,
)
from backend.blocks._ocr_match import (
    aabb_from_polygon,
    apply_output_coordinate_mode,
    empty_match_outputs,
    match_all_queries,
    parse_match_queries,
    primary_match_from_list,
    total_match_count,
)

# Keep one session for a flow. Repeatedly constructing ONNX sessions is expensive
# and can itself fragment the Windows native heap. The interpreter resets it at
# the run boundary; inference failures also reset it immediately.
_OCR_REBUILD_EVERY = 0
# Upscale tiny crops so det/rec see enough pixels (boxes scaled back after).
_OCR_MIN_SHORT_SIDE = 48
_OCR_MIN_AREA = 4000
_OCR_MAX_UPSCALE = 3.0
# Guard against accidental full-desktop tensors if region resolution misbehaves.
_OCR_MAX_SIDE = 1600
_OCR_INFER_ATTEMPTS = 3

SCHEMA = {
    "type": "ocr_recognize",
    "label": "OCR取字",
    "category": "识别类",
    "inputs": [
        {
            "name": "source_mode",
            "type": "select",
            "label": "数据来源",
            "options": ["screen", "image"],
            "default": "screen",
            "option_labels": {
                "screen": "屏幕区域",
                "image": "图片文件",
            },
        },
        {
            "name": "image_path",
            "type": "string",
            "label": "图片路径",
            "default": "",
            "placeholder": "绑定区域截图的 path",
            "show_when": {"source_mode": "image"},
        },
        {
            "name": "origin_x",
            "type": "number",
            "label": "屏幕原点 X",
            "default": 0,
            "placeholder": "绑定截图 left",
            "show_when": {"source_mode": "image"},
        },
        {
            "name": "origin_y",
            "type": "number",
            "label": "屏幕原点 Y",
            "default": 0,
            "placeholder": "绑定截图 top",
            "show_when": {"source_mode": "image"},
        },
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
            "show_when": {"source_mode": "screen"},
        },
        {
            "name": "region",
            "type": "rect",
            "label": "识别区域",
            "default": None,
            "show_when": {"source_mode": "screen", "region_mode": "rect"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "起点 X",
            "default": 0,
            "show_when": {"source_mode": "screen", "region_mode": "xy"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "起点 Y",
            "default": 0,
            "show_when": {"source_mode": "screen", "region_mode": "xy"},
        },
        {
            "name": "width",
            "type": "number",
            "label": "宽度",
            "default": 320,
            "show_when": {"source_mode": "screen", "region_mode": "xy"},
        },
        {
            "name": "height",
            "type": "number",
            "label": "高度",
            "default": 80,
            "show_when": {"source_mode": "screen", "region_mode": "xy"},
        },
        {
            "name": "anchor_template",
            "type": "string",
            "label": "锚点模板",
            "default": "",
            "placeholder": "模板图片路径",
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
        },
        {
            "name": "anchor_threshold",
            "type": "number",
            "label": "锚点阈值",
            "default": 0.8,
            "placeholder": "0~1",
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
        },
        {
            "name": "anchor_offset_x",
            "type": "number",
            "label": "锚点偏移 X",
            "default": 0,
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
        },
        {
            "name": "anchor_offset_y",
            "type": "number",
            "label": "锚点偏移 Y",
            "default": 0,
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
        },
        {
            "name": "anchor_ocr_width",
            "type": "number",
            "label": "识别宽度",
            "default": 0,
            "placeholder": "0 = 模板宽",
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
        },
        {
            "name": "anchor_ocr_height",
            "type": "number",
            "label": "识别高度",
            "default": 0,
            "placeholder": "0 = 模板高",
            "show_when": {"source_mode": "screen", "region_mode": "anchor"},
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
        {
            "name": "output_coordinate_mode",
            "type": "select",
            "label": "输出坐标",
            "options": ["screen_abs", "region_rel"],
            "default": "region_rel",
            "option_labels": {
                "screen_abs": "屏幕绝对",
                "region_rel": "区域相对",
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
        {"name": "match_count", "type": "number"},
        {"name": "text", "type": "string"},
        {"name": "confidence", "type": "number"},
        {"name": "recognized", "type": "boolean"},
        {"name": "matches", "type": "array", "canvas": False},
        {"name": "boxes", "type": "array", "canvas": False},
        {"name": "region", "type": "object", "canvas": False},
        {"name": "anchor", "type": "object", "canvas": False},
    ],
}

_ocr_engine = None
_ocr_call_count = 0
_ocr_lock = threading.Lock()
_ocr_infer_lock = threading.Lock()


def _dispose_ocr_engine(engine) -> None:
    if engine is None:
        return
    # RapidOCR 1.4.x stores detector/classifier sessions under ``infer.session``
    # and the recognizer session directly under ``session``.
    for attr in ("text_det", "text_cls", "text_rec"):
        try:
            sub = getattr(engine, attr, None)
            if sub is None:
                continue
            infer = getattr(sub, "infer", None)
            if infer is not None:
                try:
                    setattr(infer, "session", None)
                except Exception:
                    pass
            try:
                setattr(sub, "session", None)
            except Exception:
                pass
            try:
                setattr(engine, attr, None)
            except Exception:
                pass
        except Exception:
            pass
    try:
        del engine
    except Exception:
        pass
    try:
        gc.collect()
    except Exception:
        pass


def reset_ocr_engine() -> None:
    """Drop the RapidOCR/ONNX singleton so the next call rebuilds a fresh session."""
    global _ocr_engine, _ocr_call_count
    with _ocr_lock:
        engine = _ocr_engine
        _ocr_engine = None
        _ocr_call_count = 0
    _dispose_ocr_engine(engine)


def _get_ocr():
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 OCR 依赖，请执行: pip install rapidocr-onnxruntime"
                ) from exc
            _ocr_engine = RapidOCR(
                # ``min`` expands a 59x25 crop to roughly 1728x736. ``max``
                # keeps the bounded input small and avoids huge det tensors.
                det_limit_type="max",
                det_limit_side_len=_OCR_MAX_SIDE,
                intra_op_num_threads=2,
                inter_op_num_threads=1,
            )
        return _ocr_engine


def _maybe_periodic_rebuild() -> None:
    """Rebuild session every N inferences to reduce native memory buildup."""
    global _ocr_engine, _ocr_call_count
    engine = None
    with _ocr_lock:
        _ocr_call_count += 1
        if _OCR_REBUILD_EVERY > 0 and _ocr_call_count >= _OCR_REBUILD_EVERY:
            engine = _ocr_engine
            _ocr_engine = None
            _ocr_call_count = 0
    if engine is not None:
        _dispose_ocr_engine(engine)


def _is_ocr_memory_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if isinstance(exc, MemoryError):
        return True
    markers = (
        "bad allocation",
        "onnxruntime",
        "failed to allocate",
        "out of memory",
        "oom",
        "std::bad_alloc",
    )
    if any(m in msg for m in markers):
        return True
    name = type(exc).__name__.lower()
    return "onnx" in name and ("runtime" in name or "exception" in name)


def _prepare_ocr_image(img):
    """
    Scale tiny crops for readability and cap large inputs; return (image, scale).
    Caller must scale OCR box coords back by 1/scale.
    """
    try:
        w, h = img.size
    except Exception:
        return img, 1.0
    if w <= 0 or h <= 0:
        return img, 1.0
    short = min(w, h)
    area = w * h
    scale = 1.0
    if short < _OCR_MIN_SHORT_SIDE:
        scale = max(scale, _OCR_MIN_SHORT_SIDE / float(short))
    if area < _OCR_MIN_AREA:
        scale = max(scale, (_OCR_MIN_AREA / float(area)) ** 0.5)
    scale = min(scale, _OCR_MAX_UPSCALE)
    longest = max(w, h)
    if longest * scale > _OCR_MAX_SIDE:
        scale = _OCR_MAX_SIDE / float(longest)
    if scale <= 1.01:
        if scale >= 0.99:
            return img, 1.0
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    try:
        from PIL import Image

        resample = getattr(Image, "Resampling", Image).LANCZOS
    except Exception:
        resample = 1  # LANCZOS
    try:
        return img.resize((nw, nh), resample), scale
    except Exception:
        return img, 1.0


def _normalize_ocr_array(arr):
    """Ensure a small, contiguous RGB uint8 buffer for ONNX."""
    import numpy as np

    if arr is None:
        raise ValueError("OCR 输入图像为空")
    out = np.ascontiguousarray(arr)
    if out.ndim == 2:
        out = np.stack([out, out, out], axis=-1)
    elif out.ndim == 3 and out.shape[2] == 4:
        out = out[:, :, :3]
    elif out.ndim != 3 or out.shape[2] < 3:
        raise ValueError(f"OCR 输入图像形状无效: {getattr(out, 'shape', None)}")
    if out.dtype != np.uint8:
        out = out.astype(np.uint8, copy=False)
    h, w = int(out.shape[0]), int(out.shape[1])
    if h <= 0 or w <= 0:
        raise ValueError("OCR 输入图像尺寸无效")
    return out


def _clear_exception_tracebacks(exc: BaseException) -> None:
    """Break traceback references to failed native sessions before retrying."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        try:
            current.__traceback__ = None
        except Exception:
            pass
        current = current.__cause__ or current.__context__


def _infer_ocr(arr):
    """Run RapidOCR; rebuild once only after a genuine allocator failure."""
    import numpy as np

    arr = _normalize_ocr_array(arr)
    with _ocr_infer_lock:
        for attempt in range(1, _OCR_INFER_ATTEMPTS + 1):
            try:
                return _get_ocr()(arr)
            except Exception as exc:
                if not _is_ocr_memory_error(exc):
                    raise
                if attempt >= _OCR_INFER_ATTEMPTS:
                    reset_ocr_engine()
                    raise RuntimeError(
                        "OCR 引擎异常（ONNX bad allocation）。已自动重建引擎并重试，"
                        "若持续出现请重启应用。"
                    ) from exc
                # Remove traceback-held engine refs before constructing a new session.
                _clear_exception_tracebacks(exc)
                reset_ocr_engine()
                try:
                    gc.collect()
                except Exception:
                    pass
                time.sleep(0.05 * attempt)
                arr = np.ascontiguousarray(arr.copy())


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
        "match_count": 0,
        "text": "",
        "confidence": 0.0,
        "recognized": False,
        "matches": [],
        "boxes": [],
        "region": region,
        "anchor": anchor,
    }


def _load_ocr_image(params: dict):
    """Load image from path; return (PIL.Image, origin_x, origin_y, region_list)."""
    from PIL import Image

    path = str(params.get("image_path") or "").strip()
    if not path:
        raise ValueError("请设置图片路径（可绑定区域截图的 path）")
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"图片文件不存在: {path}")
    try:
        img = Image.open(p)
        img.load()
    except Exception as exc:
        raise ValueError(f"无法打开图片: {path} ({exc})") from exc

    ox = int(float(params.get("origin_x") or 0))
    oy = int(float(params.get("origin_y") or 0))
    w, h = img.size
    region = [ox, oy, ox + int(w), oy + int(h)]
    return img, ox, oy, region


def run_ocr(params: dict) -> dict:
    source = str(params.get("source_mode") or "screen").strip().lower() or "screen"
    # if_text_contains uses capture for live screen OCR
    if source in ("capture", "screen", ""):
        source = "screen"

    anchor = None
    if source == "image":
        img, ox, oy, region = _load_ocr_image(params)
        x1, y1 = ox, oy
    else:
        (x1, y1, x2, y2), anchor = resolve_ocr_region(params)
        region = [x1, y1, x2, y2]
        img = grab_region(x1, y1, x2, y2)

    import numpy as np

    ocr_img, scale = _prepare_ocr_image(img)
    # Copy out of the PIL buffer so we can close the screenshot immediately.
    arr = np.ascontiguousarray(np.asarray(ocr_img))
    try:
        result, _elapsed = _infer_ocr(arr)
    finally:
        del arr
        if ocr_img is not img:
            try:
                ocr_img.close()
            except Exception:
                pass
        try:
            img.close()
        except Exception:
            pass
        # Disabled by default; run-boundary cleanup is handled by the interpreter.
        _maybe_periodic_rebuild()

    if not result:
        return _empty_ocr_result(region, anchor)

    min_conf = float(
        params.get("min_confidence") if params.get("min_confidence") is not None else 0.3
    )
    include_geometry = str(params.get("include_box_geometry", "false")).lower() == "true"
    match_mode = str(params.get("match_mode") or "contains")
    queries = parse_match_queries(params)
    inv_scale = 1.0 / scale if scale and scale != 1.0 else 1.0

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
        if inv_scale != 1.0 and poly:
            poly = [
                [int(round(pt[0] * inv_scale)), int(round(pt[1] * inv_scale))]
                for pt in poly
            ]
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
    recognized = bool(texts)

    matches = match_all_queries(boxes, queries, match_mode) if queries else []
    match_out = primary_match_from_list(matches) if matches else empty_match_outputs()
    match_count = total_match_count(matches)

    result = {
        **match_out,
        "match_count": match_count,
        "text": joined,
        "confidence": round(avg, 4),
        "recognized": recognized,
        "matches": matches,
        "boxes": boxes,
        "region": region,
        "anchor": anchor,
    }
    return apply_output_coordinate_mode(
        result,
        mode=str(params.get("output_coordinate_mode") or "screen_abs"),
        origin_x=x1,
        origin_y=y1,
    )


def handler(params, context, **kwargs):
    return run_ocr(params)
