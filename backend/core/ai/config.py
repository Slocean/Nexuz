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
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "",
    },
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

_OPTION_KEYS = ("base_url", "api_key", "model")


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


def _preset_id(value: Any) -> str:
    s = str(value or "custom").strip() or "custom"
    return s


def _read_options(raw_ai: dict[str, Any]) -> dict[str, dict[str, str]]:
    options_raw = raw_ai.get("options") if isinstance(raw_ai.get("options"), dict) else {}
    out: dict[str, dict[str, str]] = {}
    for key, slot in options_raw.items():
        pid = _preset_id(key)
        if not isinstance(slot, dict):
            continue
        out[pid] = {
            "base_url": str(slot.get("base_url") or "").strip(),
            "api_key": str(slot.get("api_key") or "").strip(),
            "model": str(slot.get("model") or "").strip(),
        }
    return out


def _slot_from_active(cfg: AiConfig) -> dict[str, str]:
    return {
        "base_url": str(cfg.base_url or "").strip(),
        "api_key": str(cfg.api_key or "").strip(),
        "model": str(cfg.model or "").strip(),
    }


def _merge_option_slot(
    existing: dict[str, str] | None,
    patch: dict[str, Any] | None,
    *,
    keep_existing_key: bool = True,
) -> dict[str, str]:
    base = {
        "base_url": "",
        "api_key": "",
        "model": "",
    }
    if isinstance(existing, dict):
        for k in _OPTION_KEYS:
            base[k] = str(existing.get(k) or "").strip()
    patch = patch if isinstance(patch, dict) else {}
    if "base_url" in patch:
        base["base_url"] = str(patch.get("base_url") or "").strip()
    if "model" in patch:
        base["model"] = str(patch.get("model") or "").strip()
    if "api_key" in patch:
        new_key = str(patch.get("api_key") or "").strip()
        if new_key:
            base["api_key"] = new_key
        elif not keep_existing_key:
            base["api_key"] = ""
    return base


def _public_options(options: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pid, slot in options.items():
        key = str(slot.get("api_key") or "")
        out[pid] = {
            "base_url": str(slot.get("base_url") or ""),
            "model": str(slot.get("model") or ""),
            "has_api_key": bool(key.strip()),
            "api_key_masked": mask_api_key(key),
        }
    return out


def get_ai_config() -> AiConfig:
    stored = load_app_config().get("ai")
    base = AiConfig.from_dict(stored if isinstance(stored, dict) else {})
    return _apply_env_overrides(base)


def public_ai_config(cfg: AiConfig | None = None) -> dict[str, Any]:
    """Safe for frontend: no full api_key."""
    raw = load_app_config().get("ai")
    raw_ai = raw if isinstance(raw, dict) else {}
    c = cfg or get_ai_config()
    d = c.to_dict()
    key = d.pop("api_key", "") or ""
    d["has_api_key"] = bool(key.strip())
    d["api_key_masked"] = mask_api_key(key)
    d["presets"] = list(PROVIDER_PRESETS)
    options = _read_options(raw_ai)
    # Ensure active preset appears in options for UI restore.
    active_preset = _preset_id(d.get("preset"))
    if active_preset not in options:
        options[active_preset] = {
            "base_url": str(d.get("base_url") or ""),
            "api_key": str(key or ""),
            "model": str(d.get("model") or ""),
        }
    d["options"] = _public_options(options)
    return d


def set_ai_config(patch: dict[str, Any] | None) -> AiConfig:
    """
    Merge patch into stored ai config.
    Always upserts the active preset into `options` so switching vendors
    can restore previously saved base_url / api_key / model.
    If api_key is omitted / empty string and keep_existing_key is True (default),
    preserve the previously stored key (per active + per option slot).
    """
    patch = dict(patch or {})
    keep_existing = bool(patch.pop("keep_existing_key", True))
    options_patch = patch.pop("options", None)
    cfg = load_app_config()
    current_raw = cfg.get("ai") if isinstance(cfg.get("ai"), dict) else {}
    current = AiConfig.from_dict(current_raw)
    options = _read_options(current_raw)

    merged = current.to_dict()
    for key in (
        "enabled",
        "provider",
        "preset",
        "base_url",
        "model",
        "temperature",
        "timeout_s",
        "supports_vision",
        "supports_structured",
        "allow_dangerous",
        "disabled_skills",
        "context_window_tokens",
        "max_output_tokens",
    ):
        if key in patch:
            merged[key] = patch[key]

    if "api_key" in patch:
        new_key = str(patch.get("api_key") or "").strip()
        if new_key:
            merged["api_key"] = new_key
        elif not keep_existing:
            merged["api_key"] = ""
        # empty + keep_existing → leave previous key

    # Merge multi-preset option map first (may include other vendors).
    if isinstance(options_patch, dict):
        for key, slot in options_patch.items():
            pid = _preset_id(key)
            if not isinstance(slot, dict):
                continue
            options[pid] = _merge_option_slot(
                options.get(pid),
                slot,
                keep_existing_key=keep_existing,
            )

    # Normalize types via AiConfig
    normalized = AiConfig.from_dict(merged)
    active_preset = _preset_id(normalized.preset)
    # Upsert currently active slot from the merged active fields.
    active_slot_patch: dict[str, Any] = {
        "base_url": normalized.base_url,
        "model": normalized.model,
    }
    if "api_key" in patch:
        active_slot_patch["api_key"] = patch.get("api_key")
    options[active_preset] = _merge_option_slot(
        options.get(active_preset) or _slot_from_active(current),
        active_slot_patch,
        keep_existing_key=keep_existing,
    )
    # Keep active api_key in sync with its option slot when keep_existing left it blank.
    if not str(normalized.api_key or "").strip():
        slot_key = str(options[active_preset].get("api_key") or "").strip()
        if slot_key:
            normalized = AiConfig.from_dict({**normalized.to_dict(), "api_key": slot_key})

    stored = normalized.to_dict()
    stored["options"] = options
    cfg["ai"] = stored
    save_app_config(cfg)
    return _apply_env_overrides(normalized)
