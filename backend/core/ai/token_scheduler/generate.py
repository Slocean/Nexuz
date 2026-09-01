"""Guarded structured generate: plan_call → invoke → raise budget → continue."""

from __future__ import annotations

from typing import Any, Sequence

from backend.core.ai import llm_cache
from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.lc.structured_call import invoke_structured
from backend.core.ai.token_scheduler.continuation import continue_structured
from backend.core.ai.token_scheduler.guard import (
    classify_generation_failure,
    should_retry_or_continue,
)
from backend.core.ai.token_scheduler.output_planner import OutputProfile
from backend.core.ai.token_scheduler.scheduler import CallBudget, plan_call
from backend.core.ai.types import AiConfig


def _system_text_from_messages(messages: Sequence[Any]) -> str:
    parts: list[str] = []
    for m in messages or []:
        role = getattr(m, "type", None) or getattr(m, "role", None)
        # LangChain SystemMessage.type == "system"
        if str(role) == "system":
            parts.append(str(getattr(m, "content", "") or ""))
        elif isinstance(m, tuple) and len(m) >= 2 and m[0] == "system":
            parts.append(str(m[1]))
        elif isinstance(m, dict) and m.get("role") == "system":
            parts.append(str(m.get("content") or ""))
    return "\n".join(parts)


def guarded_structured_invoke(
    cfg: AiConfig | None,
    profile: OutputProfile | str,
    schema: type,
    messages: Sequence[Any],
    *,
    compact_messages: Sequence[Any] | None = None,
    temperature: float = 0.1,
    max_continues: int = 2,
    tool_overhead_tokens: int = 0,
    create_model: Any = None,
    use_cache: bool = True,
) -> Any:
    """
    Output-first dual budget + length raise once + continuation attempts.

    create_model: optional factory (defaults to create_chat_model). Callers that
    monkeypatch their module's create_chat_model should pass that symbol through.
    """
    _create = create_model or create_chat_model
    system_text = _system_text_from_messages(messages)
    last_exc: BaseException | None = None
    length_retried = False

    # 应用层结果缓存：purpose + 模型 + 消息哈希（命中可省一次真实 API 调用）。
    cache_key = ""
    if use_cache and llm_cache.enabled(cfg) and str(profile or "").strip():
        try:
            cache_key = llm_cache.make_key(
                purpose=str(profile),
                model=str(getattr(cfg, "model", "") or ""),
                base_url=str(getattr(cfg, "base_url", "") or ""),
                temperature=temperature,
                schema_name=getattr(schema, "__name__", "") or "",
                messages=messages,
            )
        except Exception:
            cache_key = ""
    if cache_key:
        hit = llm_cache.load_structured(cache_key, schema)
        if hit is not None:
            return hit

    for retry in (False, True):
        budget: CallBudget = plan_call(
            cfg,
            profile,
            system_text=system_text,
            tool_overhead_tokens=tool_overhead_tokens,
            retry=retry,
        )
        llm = _create(
            cfg,
            temperature=temperature,
            streaming=False,
            max_tokens=budget.max_tokens,
            for_structured=True,
        )
        try:
            result = invoke_structured(
                llm,
                schema,
                messages,
                compact_messages=compact_messages,
            )
            if cache_key:
                llm_cache.store_structured(cache_key, result)
            return result
        except Exception as exc:
            last_exc = exc
            kind = classify_generation_failure(exc)
            if not should_retry_or_continue(kind):
                raise
            if not retry:
                length_retried = True
                continue
            # After raise-budget still failing → continuation protocol
            for _ in range(max(0, int(max_continues))):
                cont_budget = plan_call(
                    cfg,
                    profile,
                    system_text=system_text,
                    tool_overhead_tokens=tool_overhead_tokens,
                    retry=True,
                )
                cont_llm = _create(
                    cfg,
                    temperature=temperature,
                    streaming=False,
                    max_tokens=cont_budget.max_tokens,
                    for_structured=True,
                )
                try:
                    cont_result = continue_structured(
                        cont_llm,
                        schema,
                        messages,
                        invoke_fn=invoke_structured,
                        compact_messages=compact_messages,
                    )
                    if cache_key:
                        llm_cache.store_structured(cache_key, cont_result)
                    return cont_result
                except Exception as cont_exc:
                    last_exc = cont_exc
                    if not should_retry_or_continue(classify_generation_failure(cont_exc)):
                        raise
                    continue
            break

    assert last_exc is not None
    # Annotate for callers that already raised budget
    if length_retried:
        last_exc._nexuz_length_retried = True  # type: ignore[attr-defined]
    raise last_exc
