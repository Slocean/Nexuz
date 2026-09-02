"""Model capability resolution — config-first, local/cloud defaults, weak name hints last.

名字提示 / preset 窗口表统一来自 backend/core/ai/model_capabilities.py（单一来源）。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core.ai.model_capabilities import (
    DEFAULT_CLOUD_CONTEXT,
    DEFAULT_LOCAL_CONTEXT,
    PRESET_CONTEXT as _PRESET_CONTEXT,
    is_reasoning_model,  # re-export（completion_budget / token_scheduler.__init__ 引用）
)
from backend.core.ai.types import AiConfig

_LOCAL_HOSTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
)

_SAFETY_MARGIN = 256


@dataclass(frozen=True)
class ModelCapability:
    max_context_tokens: int
    safety_margin: int
    summary_threshold: int
    retrieval_budget: int
    local: bool
    reasoning_hint: bool


def is_local_base_url(base_url: str | None) -> bool:
    raw = (base_url or "").strip()
    if not raw:
        return False
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        lower = raw.lower()
        return any(h in lower for h in _LOCAL_HOSTS)
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        try:
            second = int(parts[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    return False


def resolve_capability(cfg: AiConfig | None) -> ModelCapability:
    c = cfg
    local = is_local_base_url(c.base_url if c else None)
    reasoning = is_reasoning_model(c.model if c else None)

    explicit = None
    if c and c.context_window_tokens is not None:
        try:
            explicit = int(c.context_window_tokens)
        except (TypeError, ValueError):
            explicit = None

    if explicit is not None and explicit >= 1024:
        max_ctx = explicit
    else:
        preset = (c.preset if c else "") or "custom"
        max_ctx = _PRESET_CONTEXT.get(preset) or (
            DEFAULT_LOCAL_CONTEXT if local else DEFAULT_CLOUD_CONTEXT
        )
        if local and preset == "custom":
            max_ctx = DEFAULT_LOCAL_CONTEXT

    # Local small windows: tighter summary / retrieval; large windows loosen.
    if max_ctx <= 8_192:
        summary_threshold = 1_200
        retrieval_budget = 400
    elif max_ctx <= 32_768:
        summary_threshold = 2_800
        retrieval_budget = 800
    else:
        summary_threshold = 6_000
        retrieval_budget = 1_600

    return ModelCapability(
        max_context_tokens=int(max_ctx),
        safety_margin=_SAFETY_MARGIN,
        summary_threshold=summary_threshold,
        retrieval_budget=retrieval_budget,
        local=local,
        reasoning_hint=reasoning,
    )
