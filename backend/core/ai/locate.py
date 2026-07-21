"""Screenshot + OCR locate helpers for AI session artifacts."""

from __future__ import annotations

import base64
import io
import time
import uuid
from typing import Any, Callable

from backend.blocks._helpers import pack_point, validate_point
from backend.blocks._ocr_match import find_all_matching_boxes, match_outputs_from_box


CaptureFn = Callable[..., dict[str, Any]]


def new_shot_id() -> str:
    return f"shot_{uuid.uuid4().hex[:10]}"


def new_point_id() -> str:
    return f"pt_{uuid.uuid4().hex[:10]}"


def capture_to_artifact(
    capture_fn: CaptureFn,
    *,
    hide_window: bool = True,
) -> dict[str, Any]:
    """Call capture_desktop-like API and return artifact meta (keep data_url for UI)."""
    result = capture_fn(hide_window=hide_window)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "截图失败"}

    shot_id = new_shot_id()
    artifact = {
        "shot_id": shot_id,
        "width": int(result.get("width") or 0),
        "height": int(result.get("height") or 0),
        "left": int(result.get("left") or 0),
        "top": int(result.get("top") or 0),
        "coord_space": result.get("coord_space") or {},
        "data_url": result.get("data_url") or "",
        "size": int(result.get("size") or 0),
        "created_at": time.time(),
    }
    # Meta for the model — omit full image
    model_view = {
        "ok": True,
        "shot_id": shot_id,
        "width": artifact["width"],
        "height": artifact["height"],
        "left": artifact["left"],
        "top": artifact["top"],
        "coord_space": artifact["coord_space"],
        "note": "完整截图已存会话，请用 locate_text_on_screen(shot_ref=shot_id) 定位",
    }
    return {"ok": True, "artifact": artifact, "model_view": model_view}


def _ocr_boxes_from_data_url(data_url: str, *, offset_x: int = 0, offset_y: int = 0) -> list[dict]:
    """Run RapidOCR on a data URL image; return screen-absolute boxes."""
    from backend.blocks.ocr_recognize import _infer_ocr, _prepare_ocr_image, _compact_box
    from backend.blocks._ocr_match import aabb_from_polygon
    from PIL import Image
    import numpy as np

    if not data_url or "," not in data_url:
        raise ValueError("无效的截图 data_url")
    raw_b64 = data_url.split(",", 1)[1]
    raw = base64.b64decode(raw_b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    ocr_img, scale = _prepare_ocr_image(img)
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

    if not result:
        return []

    inv_scale = 1.0 / scale if scale and scale != 1.0 else 1.0
    boxes: list[dict] = []
    for item in result:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], item[1], float(item[2])
        if score < 0.3:
            continue
        poly = _compact_box(box)
        if inv_scale != 1.0 and poly:
            poly = [
                [int(round(pt[0] * inv_scale)), int(round(pt[1] * inv_scale))]
                for pt in poly
            ]
        geom = aabb_from_polygon(poly, offset_x=offset_x, offset_y=offset_y)
        boxes.append(
            {
                "text": text,
                "confidence": round(score, 4),
                "left": geom["left"],
                "top": geom["top"],
                "width": geom["width"],
                "height": geom["height"],
                "cx": geom["cx"],
                "cy": geom["cy"],
            }
        )
        if len(boxes) >= 120:
            break
    return boxes


def locate_text(
    artifacts: dict[str, Any],
    *,
    match_text: str,
    match_mode: str = "contains",
    shot_ref: str | None = None,
    label: str | None = None,
    capture_fn: CaptureFn | None = None,
) -> dict[str, Any]:
    """OCR-find text on a stored shot (or capture fresh), store point artifact."""
    shots = artifacts.setdefault("shots", {})
    points = artifacts.setdefault("points", {})

    shot = None
    if shot_ref and shot_ref in shots:
        shot = shots[shot_ref]
    elif shots:
        # Most recent by created_at
        shot = max(shots.values(), key=lambda s: float(s.get("created_at") or 0))
    elif capture_fn is not None:
        cap = capture_to_artifact(capture_fn, hide_window=True)
        if not cap.get("ok"):
            return {"ok": False, "error": cap.get("error") or "截图失败"}
        art = cap["artifact"]
        shots[art["shot_id"]] = art
        shot = art
    else:
        return {"ok": False, "error": "无可用截图，请先调用 capture_screen"}

    expect = (match_text or "").strip()
    if not expect:
        return {"ok": False, "error": "match_text 不能为空"}

    data_url = str(shot.get("data_url") or "")
    offset_x = int(shot.get("left") or 0)
    offset_y = int(shot.get("top") or 0)
    try:
        boxes = _ocr_boxes_from_data_url(data_url, offset_x=offset_x, offset_y=offset_y)
    except Exception as exc:
        return {"ok": False, "error": f"OCR 失败: {exc}"}

    hits = find_all_matching_boxes(boxes, expect, match_mode or "contains")
    if not hits:
        sample = [str(b.get("text") or "") for b in boxes[:12]]
        return {
            "ok": False,
            "error": f"未找到匹配文字: {expect}",
            "sample_texts": sample,
            "box_count": len(boxes),
        }

    primary = hits[0]
    out = match_outputs_from_box(primary)
    x, y = int(out["x"]), int(out["y"])
    packed = pack_point(x, y)
    pt_id = new_point_id()
    point_art = {
        "ref_id": pt_id,
        "x": x,
        "y": y,
        "packed": packed,
        "label": label or expect,
        "source": "ocr",
        "matched_text": out.get("matched_text") or expect,
        "shot_id": shot.get("shot_id"),
        "match_count": len(hits),
        "bbox": {
            "left": out["left"],
            "top": out["top"],
            "width": out["width"],
            "height": out["height"],
        },
    }
    points[pt_id] = point_art
    return {
        "ok": True,
        "point_ref": pt_id,
        "x": x,
        "y": y,
        "matched_text": point_art["matched_text"],
        "match_count": len(hits),
        "label": point_art["label"],
        "source": "ocr",
    }


def pack_point_artifact(
    artifacts: dict[str, Any],
    *,
    x: int | float,
    y: int | float,
    label: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    x_i, y_i = validate_point(int(x), int(y))
    packed = pack_point(x_i, y_i)
    pt_id = new_point_id()
    art = {
        "ref_id": pt_id,
        "x": x_i,
        "y": y_i,
        "packed": packed,
        "label": label or f"({x_i},{y_i})",
        "source": source or "manual",
    }
    artifacts.setdefault("points", {})[pt_id] = art
    return {"ok": True, "point_ref": pt_id, "x": x_i, "y": y_i, "label": art["label"], "source": art["source"]}


def apply_point_to_params(point: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge packed point into click-like params."""
    out = dict(params or {})
    packed = point.get("packed") if isinstance(point.get("packed"), dict) else {}
    out["x"] = int(point.get("x") if point.get("x") is not None else packed.get("x") or 0)
    out["y"] = int(point.get("y") if point.get("y") is not None else packed.get("y") or 0)
    if packed.get("coordinate_mode"):
        out["coordinate_mode"] = packed["coordinate_mode"]
    if packed.get("point_norm") is not None:
        out["point_norm"] = packed["point_norm"]
    if packed.get("coord_space") is not None:
        out["coord_space"] = packed["coord_space"]
    if packed.get("window_target") is not None:
        out["window_target"] = packed["window_target"]
    if packed.get("monitor_dpi") is not None:
        out["monitor_dpi"] = packed["monitor_dpi"]
    if packed.get("monitor_dpi_scale") is not None:
        out["monitor_dpi_scale"] = packed["monitor_dpi_scale"]
    out["_ai_point_ref"] = point.get("ref_id")
    out["_ai_point_source"] = point.get("source")
    return out


def override_point(
    artifacts: dict[str, Any],
    point_ref: str,
    *,
    x: int | float,
    y: int | float,
) -> dict[str, Any]:
    points = artifacts.setdefault("points", {})
    pt = points.get(point_ref)
    if not isinstance(pt, dict):
        return {"ok": False, "error": f"点位不存在: {point_ref}"}
    x_i, y_i = validate_point(int(x), int(y))
    packed = pack_point(x_i, y_i)
    pt["x"] = x_i
    pt["y"] = y_i
    pt["packed"] = packed
    pt["source"] = "user_override"
    return {"ok": True, "point_ref": point_ref, "x": x_i, "y": y_i, "source": "user_override"}
