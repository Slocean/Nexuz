from __future__ import annotations

import json
import time

from backend.blocks._helpers import interruptible_sleep

SCHEMA = {
    "type": "browser_wait",
    "description": "等待页面条件出现：元素选择器、地址包含或自定义 JS 为真。",
    "label": "浏览器等待",
    "category": "浏览器",
    "inputs": [
        {
            "name": "wait_type",
            "type": "select",
            "label": "等待条件",
            "options": ["selector", "title_contains", "ready_state"],
            "option_labels": ["元素出现", "标题包含", "页面加载完成"],
            "default": "selector",
        },
        {
            "name": "target",
            "type": "string",
            "label": "目标",
            "default": "",
            "placeholder": "CSS 选择器或标题关键词",
            "bindable": True,
            "show_when": {"wait_type": ["selector", "title_contains"]},
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "超时(ms)",
            "default": 30000,
        },
        {
            "name": "poll_ms",
            "type": "number",
            "label": "轮询间隔(ms)",
            "default": 300,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "elapsed_ms", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def _check(eng, wait_type: str, target: str) -> bool:
    if wait_type == "title_contains":
        return bool(target) and str(target) in eng.title()
    if wait_type == "ready_state":
        return str(eng.eval_js("document.readyState", timeout_ms=2000)) == "complete"
    return bool(eng.eval_js(f"!!document.querySelector({json.dumps(target, ensure_ascii=False)})", timeout_ms=2000))


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    wait_type = str(params.get("wait_type") or "selector").strip()
    target = str(params.get("target") or "").strip()
    try:
        timeout_ms = int(params.get("timeout_ms") if params.get("timeout_ms") is not None else 30000)
    except (TypeError, ValueError):
        timeout_ms = 30000
    try:
        poll = max(50, int(params.get("poll_ms") if params.get("poll_ms") is not None else 300))
    except (TypeError, ValueError):
        poll = 300

    t0 = time.perf_counter()
    deadline = t0 + max(1000, timeout_ms) / 1000.0

    from backend.core.browser.errors import BrowserError
    from backend.core.browser.session import browser_op

    last_error = ""
    while True:
        if should_stop and should_stop():
            raise InterruptedError("流程已停止")
        paused_at = None
        if cooperate is not None:
            paused_at = time.perf_counter()
            cooperate()
            if paused_at is not None:
                deadline += time.perf_counter() - paused_at
        try:
            with browser_op() as eng:
                matched = _check(eng, wait_type, target)
            last_error = ""
        except Exception as exc:  # session hiccup: keep polling until deadline
            matched = False
            last_error = str(exc)
        if matched:
            return {"ok": True, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if time.perf_counter() >= deadline:
            detail = last_error or f"wait_type={wait_type} target={target[:80]}"
            raise TimeoutError(f"浏览器等待超时({timeout_ms}ms): {detail}")
        interruptible_sleep(poll / 1000.0, should_stop, cooperate=cooperate)
