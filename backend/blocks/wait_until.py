from __future__ import annotations

import time

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
        },
        {
            "name": "region",
            "type": "rect",
            "label": "检测区域(颜色/文字)",
            "default": None,
        },
        {
            "name": "x",
            "type": "number",
            "label": "单点X(颜色可选)",
            "default": 0,
        },
        {
            "name": "y",
            "type": "number",
            "label": "单点Y(颜色可选)",
            "default": 0,
        },
        {
            "name": "target_color",
            "type": "color",
            "label": "目标颜色",
            "default": "#FF0000",
        },
        {
            "name": "tolerance",
            "type": "number",
            "label": "颜色容差",
            "default": 20,
        },
        {
            "name": "expect_text",
            "type": "string",
            "label": "期望文字(包含)",
            "default": "",
        },
        {
            "name": "expression",
            "type": "string",
            "label": "表达式(为真则继续)",
            "default": "",
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "超时毫秒(0=不限)",
            "default": 30000,
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
    ],
}


def _check(params: dict, context: dict) -> tuple[bool, str]:
    wait_type = str(params.get("wait_type") or "text")

    if wait_type == "color":
        from backend.blocks._helpers import (
            color_distance,
            pixel_color,
            region_dominant_color,
        )

        target = str(params.get("target_color") or "#FF0000")
        tol = float(params.get("tolerance") if params.get("tolerance") is not None else 20)
        region = params.get("region")
        if region:
            actual = region_dominant_color(region)
        else:
            actual = pixel_color(int(params.get("x", 0)), int(params.get("y", 0)))
        matched = color_distance(actual, target) <= tol
        return matched, f"color={actual}"

    if wait_type == "expression":
        from backend.core.expression import evaluate_expression

        expr = str(params.get("expression") or "")
        if not expr.strip():
            raise ValueError("表达式等待需要填写 expression")
        matched = bool(evaluate_expression(expr, context))
        return matched, f"expr={expr}"

    # text (default)
    from backend.blocks.ocr_recognize import run_ocr

    expect = str(params.get("expect_text") or "")
    if not expect:
        raise ValueError("文字等待需要填写 expect_text")
    ocr = run_ocr(params)
    actual = str(ocr.get("text") or "")
    matched = expect in actual
    return matched, f"text={actual[:80]}"


def handler(params, context, **kwargs):
    timeout_ms = int(params.get("timeout_ms") if params.get("timeout_ms") is not None else 30000)
    poll = max(50, int(params.get("poll_interval_ms") if params.get("poll_interval_ms") is not None else 300))
    t0 = time.perf_counter()
    deadline = None if timeout_ms <= 0 else t0 + timeout_ms / 1000.0
    detail = ""

    while True:
        matched, detail = _check(params, context)
        if matched:
            elapsed = (time.perf_counter() - t0) * 1000
            return {"ok": True, "elapsed_ms": round(elapsed, 1), "detail": detail}
        if deadline is not None and time.perf_counter() >= deadline:
            elapsed = (time.perf_counter() - t0) * 1000
            raise TimeoutError(f"条件等待超时({timeout_ms}ms): {detail}")
        # allow stop via small sleeps
        time.sleep(poll / 1000.0)
