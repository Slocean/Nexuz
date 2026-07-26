"""Legacy FlowSpec helper — no keyword / task-type routing.

Planning belongs to the LLM PlanIR path. This stub remains only so older
call sites that import `heuristic_plan_from_text` do not break.
"""

from __future__ import annotations

from backend.core.ai.lc.structured import FlowSpec


def heuristic_plan_from_text(text: str) -> FlowSpec:
    """Return an empty plan. Do not match utterances to built-in task recipes."""
    t = (text or "").strip()
    return FlowSpec(
        intent_summary=t[:80],
        needs_locate=False,
        locate_texts=[],
        clarify_questions=[],
        steps=[],
    )
