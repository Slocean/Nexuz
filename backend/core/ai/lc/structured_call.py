"""Reliable structured-output invoke for OpenAI-compatible gateways (incl. LM Studio).

Default LangChain `with_structured_output` often uses function-calling, which breaks on
broken chat templates (jinja UndefinedValue). Prefer JSON response formats that the
gateway accepts, and retry once with a compact prompt when the model hits length limits.
"""

from __future__ import annotations

from typing import Any, Sequence

# LM Studio rejects OpenAI json_object; remember for process lifetime.
_JSON_MODE_UNSUPPORTED = False


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
    """
    global _JSON_MODE_UNSUPPORTED
    methods: list[str | None] = ["json_schema"]
    if not _JSON_MODE_UNSUPPORTED:
        methods.append("json_mode")
    methods.append(None)

    last_exc: BaseException | None = None

    for method in methods:
        try:
            bound = _bind_structured(llm, schema, method)
            return bound.invoke(list(messages))
        except TypeError:
            # Older LC / model wrapper may not accept method=
            try:
                return llm.with_structured_output(schema).invoke(list(messages))
            except Exception as exc:
                last_exc = exc
                break
        except Exception as exc:
            last_exc = exc
            if _is_unsupported_json_mode(exc):
                _JSON_MODE_UNSUPPORTED = True
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
                return bound.invoke(list(compact_messages))
            except TypeError:
                try:
                    return llm.with_structured_output(schema).invoke(
                        list(compact_messages)
                    )
                except Exception as exc:
                    last_exc = exc
                    break
            except Exception as exc:
                last_exc = exc
                if _is_unsupported_json_mode(exc) or _is_tool_template_error(exc):
                    continue
                break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("structured invoke failed without exception")
