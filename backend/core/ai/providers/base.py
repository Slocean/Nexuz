"""LlmClient protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.core.ai.types import LlmTurn


@runtime_checkable
class LlmClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> LlmTurn:
        """Return assistant text (tool_calls reserved for Phase 1)."""
        ...
