"""Reliable structured-output invoke for OpenAI-compatible gateways (incl. LM Studio).

Default LangChain `with_structured_output` often uses function-calling, which breaks on
broken chat templates (jinja UndefinedValue). Prefer JSON response formats that the
gateway accepts, and retry once with a compact prompt when the model hits length limits.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from backend.core.ai.retry import DEFAULT_RETRIES, is_transient_error, with_retry

# LM Studio rejects OpenAI json_object → 跳过 json_mode 以省一次失败往返。
# 但网关配置/重启后可能恢复支持：带 TTL，过期自动重探（而非进程内永久降级）。
_JSON_MODE_UNSUPPORTED = False
_JSON_MODE_UNSUPPORTED_AT = 0.0
_JSON_MODE_REPROBE_S = 600.0


def _json_mode_unsupported() -> bool:
    """置位后 _JSON_MODE_REPROBE_S 秒内视为不支持；过期自动复位重探。"""
    if not _JSON_MODE_UNSUPPORTED:
        return False
    return (time.monotonic() - _JSON_MODE_UNSUPPORTED_AT) <= _JSON_MODE_REPROBE_S


def _mark_json_mode_unsupported() -> None:
    global _JSON_MODE_UNSUPPORTED, _JSON_MODE_UNSUPPORTED_AT
    _JSON_MODE_UNSUPPORTED = True
    _JSON_MODE_UNSUPPORTED_AT = time.monotonic()


def reset_structured_call_guards() -> None:
    """测试/诊断用：清空降级开关。"""
    global _JSON_MODE_UNSUPPORTED, _JSON_MODE_UNSUPPORTED_AT
    _JSON_MODE_UNSUPPORTED = False
    _JSON_MODE_UNSUPPORTED_AT = 0.0


def _err_text(exc: BaseException) -> str:
    return str(exc).lower()


def _is_tool_template_error(exc: BaseException) -> bool:
    msg = _err_text(exc)
    return any(
        n in msg
        for n in (
            "jinja",
            "prompt template",
            "undefinedvalue",
            "not a function",
            "does not support tools",
            "tools is not supported",
            "tool calling",
            "function calling",
            "tool_choice",
            "invalid tool",
        )
    )


def _is_unsupported_json_mode(exc: BaseException) -> bool:
    """LM Studio: response_format.type must be 'json_schema' or 'text'."""
    msg = _err_text(exc)
    return "response_format" in msg and (
        "json_schema" in msg or "json_object" in msg or "must be" in msg
    )


def is_length_limit_error(exc: BaseException) -> bool:
    """True when completion was cut by max_tokens / length limit (not full context)."""
    msg = _err_text(exc)
    return any(
        n in msg
        for n in (
            "length limit",
            "max_tokens",
            "could not parse response content as the length limit",
        )
    )


def _is_length_limit_error(exc: BaseException) -> bool:
    return is_length_limit_error(exc)


def _bind_structured(llm: Any, schema: type, method: str | None) -> Any:
    if method is None:
        return llm.with_structured_output(schema)
    return llm.with_structured_output(schema, method=method)


def invoke_structured(
    llm: Any,
    schema: type,
    messages: Sequence[Any],
    *,
    compact_messages: Sequence[Any] | None = None,
) -> Any:
    """
    Invoke structured output with gateway-friendly methods.

    Order: json_schema → json_mode (if gateway allows) → default.
    On length-limit failure, one compact retry with json_schema.
    Transient network errors (429/5xx/timeout) get unified exponential-backoff
    retry around the whole cascade (see backend/core/ai/retry.py).
    """
    return with_retry(
        lambda: _invoke_cascade(llm, schema, messages, compact_messages=compact_messages),
        retries=DEFAULT_RETRIES,
        what="invoke_structured",
    )


def _invoke_cascade(
    llm: Any,
    schema: type,
    messages: Sequence[Any],
    *,
    compact_messages: Sequence[Any] | None,
) -> Any:
    from backend.core.ai import usage_tracker

    usage_cfg = usage_tracker.runnable_config()
    methods: list[str | None] = ["json_schema"]
    if not _json_mode_unsupported():
        methods.append("json_mode")
    methods.append(None)

    last_exc: BaseException | None = None

    for method in methods:
        try:
            bound = _bind_structured(llm, schema, method)
            return bound.invoke(list(messages), config=usage_cfg)
        except TypeError:
            # Older LC / model wrapper may not accept method= or config=
            try:
                return llm.with_structured_output(schema).invoke(list(messages))
            except Exception as exc:
                last_exc = exc
                break
        except Exception as exc:
            last_exc = exc
            if is_transient_error(exc):
                break  # 网络问题换 method 无意义，交给外层统一重试
            if _is_unsupported_json_mode(exc):
                _mark_json_mode_unsupported()
                continue
            if _is_tool_template_error(exc):
                continue
            if _is_length_limit_error(exc):
                break
            # Unknown / parse errors: try next method before giving up
            continue

    if compact_messages is not None and last_exc is not None:
        for method in ("json_schema", None):
            try:
                bound = _bind_structured(llm, schema, method)
                return bound.invoke(list(compact_messages), config=usage_cfg)
            except TypeError:
                try:
                    return llm.with_structured_output(schema).invoke(list(compact_messages))
                except Exception as exc:
                    last_exc = exc
                    break
            except Exception as exc:
                last_exc = exc
                if is_transient_error(exc):
                    break  # 网络问题交给外层统一重试
                if _is_unsupported_json_mode(exc) or _is_tool_template_error(exc):
                    continue
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("structured invoke failed without exception")
