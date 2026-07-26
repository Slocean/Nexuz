"""AiConfig → LangChain ChatOpenAI (OpenAI-compatible gateways)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx
from langchain_openai import ChatOpenAI

from backend.core.ai.config import get_ai_config
from backend.core.ai.types import AiConfig, LlmError

# Models that only accept a fixed temperature (gateway 400 otherwise).
# Value is the required temperature — do NOT assume all "reasoning" models want 1.0.
# (kimi-k2.5: only 0.6; OpenAI o-series / some reasoners: 1.0)
_FIXED_TEMPERATURE: tuple[tuple[tuple[str, ...], float], ...] = (
    (("kimi", "k2.5", "k2-", "k2."), 0.6),
    (("o1", "o3", "o4", "gpt-5", "reasoner", "deepseek-r1"), 1.0),
)


def resolve_fixed_temperature(model: str | None) -> float | None:
    """Return required temperature for the model, or None if any value is ok."""
    name = (model or "").strip().lower()
    if not name:
        return None
    for markers, temp in _FIXED_TEMPERATURE:
        if any(m in name for m in markers):
            return float(temp)
    return None


def _model_requires_temperature_one(model: str) -> bool:
    """Backward-compat: True only when the fixed temp is exactly 1.0."""
    return resolve_fixed_temperature(model) == 1.0


def _normalize_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise LlmError("未配置 Base URL")
    # ChatOpenAI expects base ending at /v1 (without /chat/completions)
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")].rstrip("/")
    return url


def create_chat_model(
    cfg: AiConfig | None = None,
    *,
    temperature: float | None = None,
    streaming: bool = True,
    for_structured: bool = False,
    **kwargs: Any,
) -> ChatOpenAI:
    """Build a ChatOpenAI client from Nexuz AiConfig (OpenAI-compatible).

    for_structured=True may attach vendor knobs that reduce reasoning/thinking
    so structured JSON is less likely to be truncated by max_tokens.
    Unknown gateways ignore unsupported extra_body fields (or we skip if risky).
    """
    from backend.core.ai.lc.completion_budget import reasoning_extra_body

    c = cfg or get_ai_config()
    if not (c.base_url or "").strip():
        raise LlmError("未配置 Base URL")

    use_temp = c.temperature if temperature is None else float(temperature)
    fixed = resolve_fixed_temperature(c.model)
    if fixed is not None:
        use_temp = fixed

    base = _normalize_base_url(c.base_url)
    api_key = (c.api_key or "").strip() or "not-needed"
    timeout = float(c.timeout_s or 120.0)

    if for_structured and "extra_body" not in kwargs:
        from backend.core.ai.lc.completion_budget import is_local_base_url

        # Never send vendor thinking knobs to LM Studio / local servers
        if not is_local_base_url(c.base_url):
            extra = reasoning_extra_body(c.model)
            if extra:
                kwargs["extra_body"] = extra

    return ChatOpenAI(
        model=c.model or "gpt-4o-mini",
        api_key=api_key,
        base_url=base,
        temperature=use_temp,
        timeout=timeout,
        streaming=streaming,
        **kwargs,
    )


def test_chat_model(cfg: AiConfig | None = None) -> dict[str, Any]:
    """Ping the configured gateway; used by ai_test_connection."""
    from backend.core.ai.vision_locate import infer_supports_vision

    c = cfg or get_ai_config()
    if not (c.base_url or "").strip():
        return {"ok": False, "error": "未配置 Base URL"}
    try:
        llm = create_chat_model(c, temperature=0, streaming=False)
        msg = llm.invoke(
            [
                ("system", "Reply with exactly: ok"),
                ("user", "ping"),
            ]
        )
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            text = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        else:
            text = str(content or "")

        supports_structured = False
        try:
            from pydantic import BaseModel, Field

            class _Probe(BaseModel):
                ok: bool = Field(description="always true")

            probe = llm.with_structured_output(_Probe).invoke(
                [("user", "Return ok=true as structured data")]
            )
            supports_structured = bool(getattr(probe, "ok", True))
        except Exception:
            supports_structured = False

        vision = (
            c.supports_vision
            if c.supports_vision is not None
            else infer_supports_vision(c.model)
        )
        return {
            "ok": True,
            "model": c.model,
            "reply_preview": text[:200],
            "supports_structured": supports_structured,
            "supports_vision": bool(vision),
            "hint": (
                "模型支持结构化输出，适合编排"
                if supports_structured
                else "结构化探测失败：编排将更多依赖启发式/技能，建议换支持 JSON/schema 的模型"
            ),
        }
    except LlmError as exc:
        return {"ok": False, "error": exc.message}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def list_remote_models(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_s: float = 8.0,
    cfg: AiConfig | None = None,
) -> dict[str, Any]:
    """
    GET {base_url}/models — works for LM Studio / Ollama / OpenAI-compatible gateways.
    Returns {ok, models:[{id, owned_by?...}], base_url, error?}.
    """
    c = cfg or get_ai_config()
    raw_base = (base_url if base_url is not None else c.base_url) or ""
    try:
        base = _normalize_base_url(raw_base)
    except LlmError as exc:
        return {"ok": False, "error": exc.message, "models": [], "base_url": raw_base}

    key = (api_key if api_key is not None else c.api_key) or ""
    key = key.strip()
    # LM Studio / some local gateways require Authorization even when auth is off.
    if not key:
        key = "lm-studio"
    url = urljoin(base.rstrip("/") + "/", "models")
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
    }

    try:
        with httpx.Client(timeout=float(timeout_s)) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code >= 400:
            hint = ""
            if "127.0.0.1" in base or "localhost" in base:
                hint = "（请确认 LM Studio / Ollama 本地服务已启动，并已加载模型）"
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}: {(resp.text or '')[:200]}{hint}",
                "models": [],
                "base_url": base,
            }
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            # Ollama native sometimes differs; OpenAI compat should use data[]
            return {
                "ok": False,
                "error": "响应不是 OpenAI /models 格式（缺少 data 数组）",
                "models": [],
                "base_url": base,
            }
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or item.get("name") or "").strip()
            if not mid:
                continue
            models.append(
                {
                    "id": mid,
                    "owned_by": str(item.get("owned_by") or item.get("object") or ""),
                }
            )
        models.sort(key=lambda m: m["id"].lower())
        return {
            "ok": True,
            "models": models,
            "base_url": base,
            "count": len(models),
        }
    except httpx.ConnectError:
        return {
            "ok": False,
            "error": f"无法连接 {base} — 请先在 LM Studio 点击 Start Server（默认端口 1234）",
            "models": [],
            "base_url": base,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "models": [], "base_url": base}
