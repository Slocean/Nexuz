"""Capture / Playback provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.core.input.types import ClickTarget, ProviderCapabilities


class CaptureProvider(ABC):
    mode: str
    capabilities: ProviderCapabilities

    @abstractmethod
    def is_available(self) -> tuple[bool, str | None]:
        """Return (ok, error_message)."""

    @abstractmethod
    def start_sequence(self, *, min_interval_ms: int = 50) -> None:
        ...

    @abstractmethod
    def stop_sequence(self) -> list[dict[str, Any]]:
        """Return FlowModel-ready nodes (type + params + next wiring optional)."""

    @abstractmethod
    def pick_single(self, *, timeout_s: float = 120) -> dict[str, Any]:
        """
        Wait for one click and return:
          {ok, params?} or {ok:False, error_code, message}
        where params is click node params (ClickTarget shape).
        """


class PlaybackProvider(ABC):
    mode: str

    @abstractmethod
    def execute(self, target: ClickTarget, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform the click. Raise or return error dict on failure."""
