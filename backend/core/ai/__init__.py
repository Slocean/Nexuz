"""Flow AI — LLM client, config, and conversation management (Phase 0)."""

from __future__ import annotations

from backend.core.ai.config import (
    PROVIDER_PRESETS,
    get_ai_config,
    mask_api_key,
    public_ai_config,
    set_ai_config,
)

__all__ = [
    "PROVIDER_PRESETS",
    "get_ai_config",
    "get_session_manager",
    "mask_api_key",
    "public_ai_config",
    "set_ai_config",
]


def get_session_manager():
    """Lazy import to avoid pulling httpx when only config/store is needed."""
    from backend.core.ai.session_manager import get_session_manager as _get

    return _get()
