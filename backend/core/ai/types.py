"""Shared types for Flow AI LLM client and conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str
    timestamp: str = ""
    id: str = ""
    # Timeline of thinking + orchestration for this assistant turn.
    # [{kind: "think"|"tool", text?, name?, ok?, detail?, elapsed_ms?}, ...]
    process: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.process:
            out["process"] = self.process
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        raw_proc = data.get("process")
        process = [p for p in raw_proc if isinstance(p, dict)] if isinstance(raw_proc, list) else []
        return cls(
            id=str(data.get("id") or ""),
            role=str(data.get("role") or "user"),
            content=str(data.get("content") or ""),
            timestamp=str(data.get("timestamp") or ""),
            process=process,
        )


@dataclass
class LlmTurn:
    """One assistant turn from the provider."""

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


@dataclass
class AiConfig:
    enabled: bool = False
    provider: str = "openai_compat"
    preset: str = "custom"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    timeout_s: float = 120.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "provider": self.provider,
            "preset": self.preset,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "temperature": float(self.temperature),
            "timeout_s": float(self.timeout_s),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AiConfig:
        raw = data if isinstance(data, dict) else {}
        temp = raw.get("temperature", 0.7)
        timeout = raw.get("timeout_s", 120.0)
        try:
            temperature = float(temp)
        except (TypeError, ValueError):
            temperature = 0.7
        try:
            timeout_s = float(timeout)
        except (TypeError, ValueError):
            timeout_s = 120.0
        return cls(
            enabled=bool(raw.get("enabled", False)),
            provider=str(raw.get("provider") or "openai_compat").strip() or "openai_compat",
            preset=str(raw.get("preset") or "custom").strip() or "custom",
            base_url=str(raw.get("base_url") or "https://api.openai.com/v1").strip(),
            api_key=str(raw.get("api_key") or "").strip(),
            model=str(raw.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini",
            temperature=temperature,
            timeout_s=timeout_s,
        )


@dataclass
class ConversationMeta:
    id: str
    title: str
    created_at: str
    updated_at: str
    model: str = ""
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "message_count": int(self.message_count),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationMeta:
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or "新对话"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            model=str(data.get("model") or ""),
            message_count=int(data.get("message_count") or 0),
        )


class LlmError(Exception):
    """Provider / transport error with a user-facing message."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
