"""参数级 AI 修正（ai_refine）：节点执行前由 LLM 依据上下文修正 params。

流程作者在节点上设置 "ai_refine": true（画布/JSON 同源），解释器在变量解析后、
handler 执行前调用本模块。LLM 只输出决策位（RefinedNodeParams JSON），平台做
静态校验，校验失败保留原参数 —— 与 agent_ir 的"LLM 决策、代码执行"理念一致。

结果不落缓存：修正决策依赖本次运行的环境状态（截图/OCR 输出等），
按参数哈希命中旧值的风险大于收益。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from backend.core.block_params_validate import validate_flow_params
from backend.core.registry import BLOCK_REGISTRY

REFINE_SYSTEM = """你是 Nexuz 流程节点的参数修正器。输入：积木 schema、当前参数、本次运行的最近上下文。
只输出 JSON：{"params": {…修正后的完整参数…}, "reason": "一句话"}。

规则：
1. 只修正确需依据上下文才能确定的参数（坐标、目标文案、选项值等）；无把握时原样返回 params。
2. 禁止编造坐标数字：坐标只能引用上下文里的 {{节点.输出}} 值或当前参数已有的绑定。
3. 禁止新增 schema 之外的参数键；禁止删除必填参数。
4. 禁止输出解释文本，只输出 JSON。
"""


class RefinedNodeParams(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


def _context_digest(context: dict[str, Any], *, max_entries: int = 16) -> dict[str, Any]:
    """最近若干条上下文输出的紧凑摘要（含 $变量 与 节点输出）。"""
    from backend.core.runtime_payload import summarize_value

    out: dict[str, Any] = {}
    for key, val in list(context.items())[-max_entries:]:
        out[str(key)] = summarize_value(val, key=str(key))
    return out


def _schema_brief(block_type: str) -> dict[str, Any] | None:
    entry = BLOCK_REGISTRY.get(block_type)
    if not isinstance(entry, dict):
        return None
    schema = entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
    inputs = []
    for inp in schema.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        inputs.append(
            {
                "name": inp.get("name"),
                "type": inp.get("type"),
                "label": inp.get("label"),
                "options": inp.get("options"),
                "required": inp.get("required"),
                "default": inp.get("default"),
            }
        )
    return {
        "type": schema.get("type") or block_type,
        "label": schema.get("label"),
        "inputs": inputs,
        "outputs": schema.get("outputs") or [],
    }


def build_refine_messages(
    block_type: str,
    params: dict[str, Any],
    context: dict[str, Any],
) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.core.runtime_payload import summarize_params

    blob = json.dumps(
        {
            "block": _schema_brief(block_type),
            "current_params": summarize_params(params),
            "recent_context": _context_digest(context),
        },
        ensure_ascii=False,
        default=str,
    )
    return [SystemMessage(content=REFINE_SYSTEM), HumanMessage(content=blob)]


# 执行热路径上的同步 LLM 往返上限：超时按失败处理（保留原参数，不阻塞流程）。
_REFINE_TIMEOUT_S = 20.0


def refine_node_params(
    block_type: str,
    params: dict[str, Any],
    context: dict[str, Any],
    *,
    cfg: Any = None,
    create_model: Any = None,
    invoke_fn: Any = None,
    timeout_s: float | None = None,
) -> tuple[dict[str, Any], str] | None:
    """返回 (修正后 params, 原因)；无需修正 / AI 未启用 / 失败 → None。

    返回前已通过块级静态校验；调用方无需重复校验。
    """
    from backend.core.ai.config import get_ai_config

    c = cfg or get_ai_config()
    if not (bool(c.enabled) and str(c.base_url or "").strip()):
        return None
    btype = str(block_type or "").strip()
    if not isinstance(BLOCK_REGISTRY.get(btype), dict):
        return None

    messages = build_refine_messages(btype, params, context)
    _invoke = invoke_fn or _guarded_invoke

    from backend.core.ai import cancel as ai_cancel

    def _call() -> Any:
        return _invoke(
            c,
            "node_refine",
            RefinedNodeParams,
            messages,
            temperature=0.1,
            create_model=create_model,
        )

    try:
        finished, raw = ai_cancel.run_with_timeout(
            _call, timeout_s=float(timeout_s or _REFINE_TIMEOUT_S)
        )
    except Exception:
        return None
    if not finished:
        return None

    if hasattr(raw, "params"):
        refined = raw.params
        reason = str(getattr(raw, "reason", "") or "")
    elif isinstance(raw, dict):
        refined = raw.get("params")
        reason = str(raw.get("reason") or "")
    else:
        return None
    if not isinstance(refined, dict) or not refined:
        return None
    if refined == params:
        return None

    issues = validate_flow_params({"nodes": {"refine": {"type": btype, "params": refined}}})
    if any(i.get("level") == "error" for i in issues):
        return None
    return refined, reason


def _guarded_invoke(cfg: Any, profile: str, schema: type, messages: list[Any], **kwargs: Any) -> Any:
    from backend.core.ai.token_scheduler.generate import guarded_structured_invoke

    # 决策依赖当次运行环境，禁用结果缓存。
    return guarded_structured_invoke(
        cfg, profile, schema, messages, use_cache=False, **kwargs
    )
