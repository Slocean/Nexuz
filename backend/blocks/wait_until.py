from __future__ import annotations

import time

from backend.blocks._helpers import interruptible_sleep

from backend.blocks._helpers import interruptible_sleep

SCHEMA = {
    "type": "wait_until",
    "label": "条件等待",
    "category": "动作类",
    "inputs": [
        {
            "name": "wait_type",
            "type": "select",
            "label": "等待类型",
            "options": ["color", "text", "expression"],
            "default": "text",
            "option_labels": {
                "color": "颜色出现",
                "text": "文字出现",
                "expression": "表达式为真",
            },
        },
        {
            "name": "region",
            "type": "rect",
            "label": "检测区域",
            "default": None,
            "show_when": {"wait_type": ["color", "text"]},
        },
        {
            "name": "x",
            "type": "number",
            "label": "单点 X",
            "default": 0,
            "show_when": {"wait_type": "color"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "单点 Y",
            "default": 0,
            "show_when": {"wait_type": "color"},
        },
        {
            "name": "target_color",
            "type": "color",
            "label": "目标颜色",
            "default": "#FF0000",
            "show_when": {"wait_type": "color"},
        },
        {
            "name": "tolerance",
            "type": "number",
            "label": "颜色容差",
            "default": 20,
            "show_when": {"wait_type": "color"},
        },
        {
            "name": "expect_text",
            "type": "string",
            "label": "期望文字",
            "default": "",
            "show_when": {"wait_type": "text"},
            "placeholder": "要等待出现的字",
        },
        {
            "name": "match_mode",
            "type": "select",
            "label": "匹配模式",
            "options": ["contains", "exact", "regex"],
            "default": "contains",
            "show_when": {"wait_type": "text"},
        },
        {
            "name": "expression",
            "type": "string",
            "label": "表达式",
            "default": "",
            "bindable": False,
            "ui": "expression",
            "show_when": {"wait_type": "expression"},
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "超时毫秒",
            "default": 30000,
            "placeholder": "0 = 不限",
        },
        {
            "name": "poll_interval_ms",
            "type": "number",
            "label": "轮询间隔毫秒",
            "default": 300,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "elapsed_ms", "type": "number"},
        {"name": "detail", "type": "string"},
        {"name": "found", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "left", "type": "number"},
        {"name": "top", "type": "number"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "matched_text", "type": "string"},
    ],
}


def _empty_coords() -> dict:
    return {
        "found": False,
        "x": 0,
        "y": 0,
        "left": 0,
        "top": 0,
        "width": 0,
        "height": 0,
        "matched_text": "",
    }


def _check(params: dict, context: dict) -> tuple[bool, str, dict]:
    wait_type = str(params.get("wait_type") or "text")

    if wait_type == "color":
        from backend.blocks._helpers import (
            color_distance,
            pixel_color,
            region_dominant_color,
            resolve_point,
            resolve_region_from_params,
        )

        target = str(params.get("target_color") or "#FF0000")
        tol = float(params.get("tolerance") if params.get("tolerance") is not None else 20)
        region = resolve_region_from_params(params)
        if region:
            actual = region_dominant_color(region)
            cx = (region[0] + region[2]) // 2
            cy = (region[1] + region[3]) // 2
            coords = {
                "found": True,
                "x": cx,
                "y": cy,
                "left": region[0],
                "top": region[1],
                "width": region[2] - region[0],
                "height": region[3] - region[1],
                "matched_text": "",
            }
        else:
            x, y = resolve_point(params)
            actual = pixel_color(x, y)
            coords = {
                "found": True,
                "x": x,
                "y": y,
                "left": x,
                "top": y,
                "width": 0,
                "height": 0,
                "matched_text": "",
            }
        matched = color_distance(actual, target) <= tol
        if not matched:
            coords = _empty_coords()
        return matched, f"color={actual}", coords

    if wait_type == "expression":
        from backend.core.expression import evaluate_expression

        expr = str(params.get("expression") or "")
        if not expr.strip():
            raise ValueError("表达式等待需要填写 expression")
        matched = bool(evaluate_expression(expr, context))
        return matched, f"expr={expr}", _empty_coords()

    # text (default)
    from backend.blocks._ocr_match import match_text
    from backend.blocks.ocr_recognize import run_ocr

    expect = str(params.get("expect_text") or "")
    if not expect:
        raise ValueError("文字等待需要填写 expect_text")
    mode = str(params.get("match_mode") or "contains")
    ocr = run_ocr({**params, "match_text": expect, "match_mode": mode})
    actual = str(ocr.get("text") or "")
    # Prefer box hit; fall back to joined-text match (legacy wait behavior).
    box_found = bool(ocr.get("found"))
    text_matched = match_text(actual, expect, mode)
    matched = box_found or text_matched
    if box_found:
        coords = {
            "found": True,
            "x": int(ocr.get("x") or 0),
            "y": int(ocr.get("y") or 0),
            "left": int(ocr.get("left") or 0),
            "top": int(ocr.get("top") or 0),
            "width": int(ocr.get("width") or 0),
            "height": int(ocr.get("height") or 0),
            "matched_text": str(ocr.get("matched_text") or ""),
        }
    else:
        coords = _empty_coords()
        if matched:
            coords["found"] = False
            coords["matched_text"] = actual[:120]
    return matched, f"text={actual[:80]}", coords


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    timeout_ms = int(params.get("timeout_ms") if params.get("timeout_ms") is not None else 30000)
    poll = max(50, int(params.get("poll_interval_ms") if params.get("poll_interval_ms") is not None else 300))
    t0 = time.perf_counter()
    deadline = None if timeout_ms <= 0 else t0 + timeout_ms / 1000.0
    detail = ""
    coords = _empty_coords()

    while True:
        if should_stop and should_stop():
            raise InterruptedError("流程已停止")
        if cooperate is not None:
            paused_at = time.perf_counter()
            cooperate()
            if deadline is not None:
                # Pause time must not burn the wait timeout.
                deadline += time.perf_counter() - paused_at
        matched, detail, coords = _check(params, context)
        if matched:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "ok": True,
                "elapsed_ms": round(elapsed, 1),
                "detail": detail,
                **coords,
            }
        if deadline is not None and time.perf_counter() >= deadline:
            elapsed = (time.perf_counter() - t0) * 1000
            raise TimeoutError(f"条件等待超时({timeout_ms}ms): {detail}")
        interruptible_sleep(poll / 1000.0, should_stop, cooperate=cooperate)
