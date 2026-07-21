"""Anthropic Messages API adapter — reserved for a later phase."""

from __future__ import annotations

from backend.core.ai.types import LlmError, LlmTurn


class AnthropicClient:
    """Placeholder: Phase 0 uses OpenAI-compatible endpoints only."""

    def chat(self, messages, *, model=None, temperature=None) -> LlmTurn:  # noqa: ANN001
        raise LlmError("Anthropic 原生协议尚未实现，请使用 OpenAI 兼容 Base URL")
