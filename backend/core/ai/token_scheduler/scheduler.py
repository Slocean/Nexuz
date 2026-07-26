"""BudgetScheduler — single entry: lock output first, then derive input capacity."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.ai.token_scheduler.capability import ModelCapability, resolve_capability
from backend.core.ai.token_scheduler.estimate import estimate_tokens
from backend.core.ai.token_scheduler.output_planner import OutputProfile, plan_output_tokens
from backend.core.ai.types import AiConfig


@dataclass(frozen=True)
class CallBudget:
    profile: str
    max_context_tokens: int
    reserved_output_tokens: int
    max_tokens: int
    available_input: int
    safety_margin: int
    summary_threshold: int
    retrieval_budget: int
    local: bool
    system_tokens: int
    tool_overhead_tokens: int
    retry: bool


def plan_call(
    cfg: AiConfig | None,
    profile: OutputProfile | str,
    *,
    system_text: str = "",
    tool_overhead_tokens: int = 0,
    retry: bool = False,
) -> CallBudget:
    """
    Unified dual-budget decision.

    available_input =
      max_context - reserved_output - safety - system - tool_overhead
    """
    caps: ModelCapability = resolve_capability(cfg)
    reserved = plan_output_tokens(cfg, profile, retry=retry, caps=caps)
    system_tok = estimate_tokens(system_text)
    tool_oh = max(0, int(tool_overhead_tokens or 0))
    available = (
        caps.max_context_tokens
        - reserved
        - caps.safety_margin
        - system_tok
        - tool_oh
    )
    available = max(256, int(available))
    return CallBudget(
        profile=str(profile or "understand"),
        max_context_tokens=caps.max_context_tokens,
        reserved_output_tokens=reserved,
        max_tokens=reserved,
        available_input=available,
        safety_margin=caps.safety_margin,
        summary_threshold=caps.summary_threshold,
        retrieval_budget=caps.retrieval_budget,
        local=caps.local,
        system_tokens=system_tok,
        tool_overhead_tokens=tool_oh,
        retry=bool(retry),
    )
