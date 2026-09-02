"""AI run_block：AI 会话内实时执行单个积木 handler（区别于 draft_* 写草稿）。

安全模型（拒绝默认）：
- SAFE：只读 / 观察 / 纯上下文类（截图、OCR、取色、找图、等待、赋值、通知），
  开启 allow_run_block 后可直接执行；
- ACTION：有真实桌面 / 外部副作用（点击、按键、文件、网络、剪贴板…），
  在 allow_run_block 之上还需 allow_dangerous；
- 其余一律拒绝：控制流（if_* / loop_* / switch / try_catch，语义归解释器）、
  CRITICAL（python_script / run_command，硬线）、用户插件（trust_tier=user_plugin）、
  未知类型（新积木未纳入白名单前不可执行）。

每次调用使用会话级 run_ctx（{"context": dict, "counter": int}）：输出按
"{node_id}.{output}" 约定写入 context，供后续调用的 {{...}} 变量解析，
与解释器的节点上下文约定一致。
"""

from __future__ import annotations

import threading
from typing import Any

from backend.core.block_params_validate import validate_flow_params
from backend.core.registry import BLOCK_REGISTRY
from backend.core.runtime_payload import summarize_result
from backend.core.variable_resolver import resolve_variables

# 允许 AI 直接实时执行的积木（只读 / 无桌面副作用）。
RUN_BLOCK_SAFE = frozenset(
    {
        "assign",
        "delay",
        "notify",
        "screenshot",
        "ocr_recognize",
        "locate_text",
        "color_detect",
        "find_image",
        "wait_until",
        "window_wait",
        "browser_extract",
        "browser_screenshot",
        "browser_wait",
        "browser_close",
    }
)

# 有真实副作用的积木：allow_run_block + allow_dangerous 双闸后才可执行。
RUN_BLOCK_ACTION = frozenset(
    {
        "click",
        "mouse_hover",
        "drag",
        "mouse_scroll",
        "key_press",
        "type_text",
        "clipboard",
        "window_activate",
        "window_close",
        "http_request",
        "file_io",
        "call_subflow",
        "schedule_trigger",
        "image_generate",
        "image_rename",
        "image_scale",
        "transparent_cut",
        "sprite_sheet_cut",
        "browser_navigate",
        "browser_click",
        "browser_fill",
        "browser_eval",
    }
)

# 单次执行墙钟上限（防 AI 传超长等待卡住会话线程）。
_MAX_DELAY_MS = 60_000.0
# handler 墙钟上限：协作型积木（delay/wait_*）受 _clamp_wait 钳制可自然完成，
# 此上限兜底卡死的 handler（网络挂起等）；MCP 客户端默认超时 120s > 90s。
_HANDLER_TIMEOUT_S = 90.0

# 等待类积木的时长参数钳制：(参数名, 上限)。timeout<=0 视为无限等待，一并钳制。
_WAIT_PARAM_CAPS: dict[str, tuple[str, float]] = {
    "delay": ("ms", _MAX_DELAY_MS),
    "wait_until": ("timeout_ms", _MAX_DELAY_MS),
    "browser_wait": ("timeout_ms", _MAX_DELAY_MS),
    "window_wait": ("timeout_sec", 60.0),
}


def classify_run_block(block_type: Any) -> str | None:
    """返回 "safe" / "action"；None = 不允许 AI 实时执行。"""
    t = str(block_type or "").strip()
    if not t:
        return None
    if t in RUN_BLOCK_SAFE:
        return "safe"
    if t in RUN_BLOCK_ACTION:
        return "action"
    return None


def _clamp_wait(btype: str, params: dict[str, Any]) -> None:
    cap = _WAIT_PARAM_CAPS.get(btype)
    if cap is None:
        return
    key, limit = cap
    try:
        val = float(params.get(key))
    except (TypeError, ValueError):
        return
    if val <= 0 or val > limit:
        params[key] = limit


def run_block_once(
    args: dict[str, Any],
    *,
    run_ctx: dict[str, Any],
    allow_run_block: bool = False,
    allow_dangerous: bool = False,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """执行一个积木并返回紧凑结果。args: {type, params}。

    timeout_s：handler 墙钟上限（默认 _HANDLER_TIMEOUT_S）；超时返回
    {"ok": False, "timed_out": True}，弃置的 handler 线程靠 should_stop 自行退出。
    """
    btype = str(args.get("type") or "").strip()
    entry = BLOCK_REGISTRY.get(btype)
    if not isinstance(entry, dict):
        return {"ok": False, "error": f"未知积木: {btype}"}

    schema = entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
    if schema.get("trust_tier") == "user_plugin":
        return {"ok": False, "error": "自定义积木不允许 AI 实时执行"}

    tier = classify_run_block(btype)
    if tier is None:
        return {
            "ok": False,
            "error": f"积木 {btype} 不支持 AI 实时执行（控制流 / 敏感类 / 未列入白名单）",
        }
    if not allow_run_block:
        return {
            "ok": False,
            "error": "AI 实时执行未开启：请在 设置 → Nexuz AI 中启用「允许 AI 实时执行积木」",
        }
    if tier == "action" and not allow_dangerous:
        return {
            "ok": False,
            "error": f"积木 {btype} 有真实副作用，需要同时开启危险模式（allow_dangerous）才能由 AI 执行",
        }

    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    issues = validate_flow_params({"nodes": {"ai_run": {"type": btype, "params": params}}})
    errors = [i for i in issues if i.get("level") == "error"]
    if errors:
        detail = "；".join(str(i.get("message")) for i in errors[:3])
        return {"ok": False, "error": f"参数校验失败：{detail}"}

    ctx = run_ctx.setdefault("context", {})
    counter = int(run_ctx.get("counter", 0)) + 1
    run_ctx["counter"] = counter
    node_id = f"ai_run_{counter}"
    try:
        params = resolve_variables(params, ctx)
    except Exception as exc:
        return {"ok": False, "error": f"变量解析失败: {exc}", "node_id": node_id}

    _clamp_wait(btype, params)
    handler = entry.get("handler")
    if not callable(handler):
        return {"ok": False, "error": f"积木 {btype} 无可执行 handler（控制流类）"}

    from backend.core.ai import cancel as ai_cancel

    stop_event = threading.Event()

    def _invoke_handler() -> dict[str, Any]:
        return handler(
            params,
            ctx,
            node={"type": btype, "params": params, "id": node_id},
            node_id=node_id,
            flow={},
            emit=lambda *a, **k: None,
            should_stop=stop_event.is_set,
            cooperate=lambda: None,
        ) or {}

    try:
        timeout_s = float(timeout_s) if timeout_s else _HANDLER_TIMEOUT_S
        finished, result = ai_cancel.run_with_timeout(
            _invoke_handler, timeout_s=timeout_s
        )
    except Exception as exc:
        return {"ok": False, "error": f"{btype} 执行失败: {exc}", "node_id": node_id}
    if not finished:
        # 通知协作型积木（should_stop）尽快自行退出并释放资源/锁
        stop_event.set()
        return {
            "ok": False,
            "timed_out": True,
            "error": f"{btype} 执行超时（>{timeout_s:.0f}s），已中止等待",
            "node_id": node_id,
            "tier": tier,
        }

    for out_name, val in (result or {}).items():
        ctx[f"{node_id}.{out_name}"] = val
    return {
        "ok": True,
        "type": btype,
        "node_id": node_id,
        "tier": tier,
        "result": summarize_result(result),
    }
