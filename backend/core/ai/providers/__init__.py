"""LLM provider adapters."""

from __future__ import annotations

from backend.core.ai.providers.base import LlmClient

__all__ = ["LlmClient", "OpenAiCompatClient"]


def __getattr__(name: str):
    if name == "OpenAiCompatClient":
        from backend.core.ai.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
