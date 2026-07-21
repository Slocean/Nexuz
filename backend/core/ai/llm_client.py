"""Factory: build LlmClient from AiConfig."""

from __future__ import annotations

from backend.core.ai.config import get_ai_config
from backend.core.ai.providers.base import LlmClient
from backend.core.ai.providers.openai_compat import OpenAiCompatClient
from backend.core.ai.types import AiConfig, LlmError


def create_llm_client(cfg: AiConfig | None = None) -> LlmClient:
    c = cfg or get_ai_config()
    provider = (c.provider or "openai_compat").strip().lower()
    if provider in ("openai_compat", "openai", "compat"):
        return OpenAiCompatClient(
            base_url=c.base_url,
            api_key=c.api_key,
            model=c.model,
            temperature=c.temperature,
            timeout_s=c.timeout_s,
        )
    if provider == "anthropic":
        raise LlmError("Anthropic 原生协议尚未实现，请将 Provider 设为 openai_compat")
    if provider == "gemini":
        raise LlmError("Gemini 原生协议尚未实现，请将 Provider 设为 openai_compat")
    raise LlmError(f"未知 Provider: {provider}")
