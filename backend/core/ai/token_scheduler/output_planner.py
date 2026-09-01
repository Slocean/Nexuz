"""OutputPlanner — lock completion budget by output_profile before packing input."""

from __future__ import annotations

from typing import Literal

from backend.core.ai.token_scheduler.capability import ModelCapability, resolve_capability
from backend.core.ai.types import AiConfig

OutputProfile = Literal[
    "understand",
    "plan_ir",
    "repair",
    "patch",
    "summarize",
    "tighten",
    "node_refine",
]

# profile → (local, cloud, reasoning_hint)
_PROFILE_TABLE: dict[str, tuple[int, int, int]] = {
    "understand": (512, 1024, 4096),
    "plan_ir": (512, 1024, 4096),
    "repair": (512, 1024, 2048),
    "patch": (512, 1024, 2048),
    "summarize": (512, 768, 1536),
    "tighten": (256, 256, 384),
    "node_refine": (512, 768, 2048),
}

_RETRY_CAP = 8192


def plan_output_tokens(
    cfg: AiConfig | None,
    profile: OutputProfile | str,
    *,
    retry: bool = False,
    caps: ModelCapability | None = None,
) -> int:
    """Estimate/lock completion tokens for this call (before packing input)."""
    c = cfg
    capability = caps or resolve_capability(c)
    table = _PROFILE_TABLE.get(str(profile) or "understand") or _PROFILE_TABLE["understand"]
    local_n, cloud_n, reason_n = table

    if capability.local and not capability.reasoning_hint:
        n = local_n
    elif capability.reasoning_hint:
        n = reason_n if not capability.local else max(local_n * 2, min(reason_n, 2048))
    else:
        n = cloud_n

    # User hard ceiling (first attempt). Retry may lift up to _RETRY_CAP.
    hard: int | None = None
    if c and c.max_output_tokens is not None:
        try:
            hard = int(c.max_output_tokens)
            if hard < 64:
                hard = None
        except (TypeError, ValueError):
            hard = None
    if hard is not None and not retry:
        n = min(n, hard)

    # Never reserve more than half the window
    n = min(n, max(256, capability.max_context_tokens // 2))

    if retry:
        n = min(_RETRY_CAP, max(n * 2, n + 512))
        n = min(n, max(256, capability.max_context_tokens // 2))

    return int(n)
