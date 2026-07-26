"""GenerationGuard — detect truncated / incomplete structured generations."""

from __future__ import annotations

from typing import Literal

FailureKind = Literal["length", "incomplete_json", "other"]


def is_length_limit_error(exc: BaseException | str) -> bool:
    """True when completion was cut by max_tokens / length limit (not full context)."""
    msg = str(exc).lower()
    return any(
        n in msg
        for n in (
            "length limit",
            "max_tokens",
            "could not parse response content as the length limit",
        )
    )


def is_incomplete_json_text(text: str | None) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.startswith("{") or s.startswith("["):
        opens = s.count("{") + s.count("[")
        closes = s.count("}") + s.count("]")
        if opens > closes:
            return True
        if not (s.endswith("}") or s.endswith("]")):
            return True
    return False


def classify_generation_failure(
    exc: BaseException | None = None,
    *,
    text: str | None = None,
) -> FailureKind:
    if exc is not None and is_length_limit_error(exc):
        return "length"
    if text is not None and is_incomplete_json_text(text):
        return "incomplete_json"
    msg = str(exc or "").lower()
    if "json" in msg and any(
        k in msg for k in ("parse", "valid", "expect", "eof", "unterminated")
    ):
        return "incomplete_json"
    return "other"


def should_retry_or_continue(kind: FailureKind) -> bool:
    return kind in ("length", "incomplete_json")
