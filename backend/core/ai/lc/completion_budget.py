"""Compatibility shim — completion budgets live in token_scheduler."""

from __future__ import annotations

from typing import Any, Literal

from backend.core.ai.token_scheduler.capability import (
    is_local_base_url,
    is_reasoning_model,
)
from backend.core.ai.token_scheduler.output_planner import plan_output_tokens
from backend.core.ai.types import AiConfig

Purpose = Literal[
    "understand",
    "plan_ir",
    "repair",
    "patch",
    "summarize",
]


def resolve_max_tokens(
    cfg: AiConfig | None,
    purpose: Purpose | str,
    *,
    retry: bool = False,
) -> int:
    """Pick max_tokens for a structured/completion call (delegates to OutputPlanner)."""
    return plan_output_tokens(cfg, purpose, retry=retry)


def reasoning_extra_body(model: str | None) -> dict[str, Any] | None:
    """
    Optional vendor knobs to reduce thinking on structured calls.
    Return None when unknown — callers must not send empty junk.
    """
    if not is_reasoning_model(model):
        return None
    name = (model or "").strip().lower()
    if "kimi" in name or "k2" in name:
        return {"thinking": {"type": "disabled"}}
    if any(m in name for m in ("o1", "o3", "o4", "gpt-5")):
        return {"reasoning_effort": "low"}
    return None


__all__ = [
    "Purpose",
    "is_local_base_url",
    "is_reasoning_model",
    "reasoning_extra_body",
    "resolve_max_tokens",
]
