"""Model capability table — config-first, local/cloud defaults, weak name hints last."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core.ai.types import AiConfig

_LOCAL_HOSTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
)

# Weak defaults when user never set context_window_tokens.
# Keyed by AiConfig.preset id — not by every new model id.
_PRESET_CONTEXT: dict[str, int] = {
    "openai": 128_000,
    "deepseek": 64_000,
    "dashscope": 32_000,
    "moonshot": 32_000,
    "zhipu": 128_000,
    "ollama": 8_192,
    "lmstudio": 8_192,
    "custom": 32_000,
}

_DEFAULT_LOCAL_CONTEXT = 8_192
_DEFAULT_CLOUD_CONTEXT = 32_768
_SAFETY_MARGIN = 256

# Optional weak lift for unfinished output when user left max_output unset.
_REASONING_MARKERS = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "reasoner",
    "deepseek-r1",
    "deepseek-reasoner",
    "kimi",
    "k2.5",
    "k2-",
    "k2.",
    "qwq",
    "thinking",
)


@dataclass(frozen=True)
class ModelCapability:
    max_context_tokens: int
    safety_margin: int
    summary_threshold: int
    retrieval_budget: int
    local: bool
    reasoning_hint: bool


def is_local_base_url(base_url: str | None) -> bool:
    raw = (base_url or "").strip()
    if not raw:
        return False
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        lower = raw.lower()
        return any(h in lower for h in _LOCAL_HOSTS)
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        try:
            second = int(parts[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    return False


def is_reasoning_model(model: str | None) -> bool:
    """Weak name hint only — never the sole budget authority."""
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(m in name for m in _REASONING_MARKERS)


def resolve_capability(cfg: AiConfig | None) -> ModelCapability:
    c = cfg
    local = is_local_base_url(c.base_url if c else None)
    reasoning = is_reasoning_model(c.model if c else None)

    explicit = None
    if c and c.context_window_tokens is not None:
        try:
            explicit = int(c.context_window_tokens)
        except (TypeError, ValueError):
            explicit = None

    if explicit is not None and explicit >= 1024:
        max_ctx = explicit
    else:
        preset = (c.preset if c else "") or "custom"
        max_ctx = _PRESET_CONTEXT.get(preset) or (
            _DEFAULT_LOCAL_CONTEXT if local else _DEFAULT_CLOUD_CONTEXT
        )
        if local and preset == "custom":
            max_ctx = _DEFAULT_LOCAL_CONTEXT

    # Local small windows: tighter summary / retrieval; large windows loosen.
    if max_ctx <= 8_192:
        summary_threshold = 1_200
        retrieval_budget = 400
    elif max_ctx <= 32_768:
        summary_threshold = 2_800
        retrieval_budget = 800
    else:
        summary_threshold = 6_000
        retrieval_budget = 1_600

    return ModelCapability(
        max_context_tokens=int(max_ctx),
        safety_margin=_SAFETY_MARGIN,
        summary_threshold=summary_threshold,
        retrieval_budget=retrieval_budget,
        local=local,
        reasoning_hint=reasoning,
    )
