"""LlmClient protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.core.ai.types import LlmTurn


@runtime_checkable
class LlmClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmTurn:
        """Return assistant text and/or tool_calls."""
        ...
