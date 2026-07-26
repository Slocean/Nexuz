"""ContinuationEngine — resume truncated structured JSON generations."""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import HumanMessage


def build_continuation_messages(
    messages: Sequence[Any],
    *,
    partial_text: str | None = None,
) -> list[Any]:
    """Append a continue instruction; keep original schema constraints in system."""
    out = list(messages)
    hint = (
        "上次输出因长度上限被截断，未能得到完整合法 JSON。"
        "请重新输出完整对象（同一 schema），字段尽量短，必须正确闭合。"
        "不要解释，不要 markdown。"
    )
    if partial_text and partial_text.strip():
        tail = partial_text.strip()[-800:]
        hint += f"\n\n已截断片段（仅供参考，请输出完整新 JSON）：\n{tail}"
    out.append(HumanMessage(content=hint))
    return out


def continue_structured(
    llm: Any,
    schema: type,
    messages: Sequence[Any],
    *,
    invoke_fn: Any,
    compact_messages: Sequence[Any] | None = None,
    partial_text: str | None = None,
) -> Any:
    """One continuation attempt via invoke_fn (usually invoke_structured)."""
    cont = build_continuation_messages(messages, partial_text=partial_text)
    compact_cont = None
    if compact_messages is not None:
        compact_cont = build_continuation_messages(
            compact_messages, partial_text=partial_text
        )
    return invoke_fn(
        llm,
        schema,
        cont,
        compact_messages=compact_cont,
    )
