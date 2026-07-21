"""AI config: config.json `ai` section + NEXUZ_AI_* env overrides."""

from __future__ import annotations

import os
from typing import Any

from backend.core.ai.types import AiConfig
from backend.paths import load_app_config, save_app_config

# Built-in OpenAI-compatible presets (base_url only; model is user-editable).
PROVIDER_PRESETS: list[dict[str, str]] = [
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {
        "id": "dashscope",
        "label": "通义（兼容）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    {"id": "moonshot", "label": "Moonshot", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {
        "id": "zhipu",
        "label": "智谱（兼容）",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    {"id": "ollama", "label": "Ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.2"},
    {"id": "custom", "label": "自定义", "base_url": "", "model": ""},
]

_ENV_MAP = {
    "enabled": "NEXUZ_AI_ENABLED",
    "provider": "NEXUZ_AI_PROVIDER",
    "preset": "NEXUZ_AI_PRESET",
    "base_url": "NEXUZ_AI_BASE_URL",
    "api_key": "NEXUZ_AI_API_KEY",
    "model": "NEXUZ_AI_MODEL",
    "temperature": "NEXUZ_AI_TEMPERATURE",
    "timeout_s": "NEXUZ_AI_TIMEOUT_S",
}


def mask_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return f"{'*' * max(4, len(key) - 4)}{key[-4:]}"


def _apply_env_overrides(cfg: AiConfig) -> AiConfig:
    data = cfg.to_dict()
    for field, env_name in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        if field == "enabled":
            data["enabled"] = raw.strip().lower() in ("1", "true", "yes", "on")
        elif field in ("temperature", "timeout_s"):
            try:
                data[field] = float(raw)
            except ValueError:
                pass
        else:
            data[field] = raw.strip()
    return AiConfig.from_dict(data)


def get_ai_config() -> AiConfig:
    stored = load_app_config().get("ai")
    base = AiConfig.from_dict(stored if isinstance(stored, dict) else {})
    return _apply_env_overrides(base)


def public_ai_config(cfg: AiConfig | None = None) -> dict[str, Any]:
    """Safe for frontend: no full api_key."""
    c = cfg or get_ai_config()
    d = c.to_dict()
    key = d.pop("api_key", "") or ""
    d["has_api_key"] = bool(key.strip())
    d["api_key_masked"] = mask_api_key(key)
    d["presets"] = list(PROVIDER_PRESETS)
    return d


def set_ai_config(patch: dict[str, Any] | None) -> AiConfig:
    """
    Merge patch into stored ai config.
    If api_key is omitted / empty string and keep_existing_key is True (default),
    preserve the previously stored key.
    """
    patch = dict(patch or {})
    keep_existing = bool(patch.pop("keep_existing_key", True))
    cfg = load_app_config()
    current_raw = cfg.get("ai") if isinstance(cfg.get("ai"), dict) else {}
    current = AiConfig.from_dict(current_raw)

    merged = current.to_dict()
    for key in ("enabled", "provider", "preset", "base_url", "model", "temperature", "timeout_s"):
        if key in patch:
            merged[key] = patch[key]

    if "api_key" in patch:
        new_key = str(patch.get("api_key") or "").strip()
        if new_key:
            merged["api_key"] = new_key
        elif not keep_existing:
            merged["api_key"] = ""
        # empty + keep_existing → leave previous key

    # Normalize types via AiConfig
    normalized = AiConfig.from_dict(merged)
    cfg["ai"] = normalized.to_dict()
    save_app_config(cfg)
    return _apply_env_overrides(normalized)
