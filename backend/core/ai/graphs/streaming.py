"""Map LangGraph / LangChain stream events → Nexuz ai_progress payloads."""

from __future__ import annotations

import time
from typing import Any, Callable

from backend.core.ai.cancel import TurnCancelled
from backend.core.ai.retry import (
    DEFAULT_BASE_DELAY,
    DEFAULT_RETRIES,
    is_transient_error,
    retry_delay,
)

ProgressFn = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


def emit_process(
    on_progress: ProgressFn | None,
    process: list[dict[str, Any]],
    step: dict[str, Any],
    *,
    mode: str,
    conversation_id: str,
    assistant_id: str,
) -> None:
    process.append(step)
    if on_progress:
        on_progress(
            {
                "type": "process",
                "mode": mode,
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
                "step": step,
                "process": list(process),
                "node": step.get("node"),
            }
        )


def emit_delta(
    on_progress: ProgressFn | None,
    *,
    mode: str,
    conversation_id: str,
    assistant_id: str,
    text: str,
    replace: bool = False,
    ev_type: str = "delta",
) -> None:
    if not on_progress:
        return
    payload: dict[str, Any] = {
        "type": ev_type,
        "mode": mode,
        "conversation_id": conversation_id,
        "assistant_id": assistant_id,
        "text": text,
    }
    if replace:
        payload["replace"] = True
    on_progress(payload)


def stream_chat_model(
    llm: Any,
    messages: list[Any],
    *,
    on_progress: ProgressFn | None,
    mode: str,
    conversation_id: str,
    assistant_id: str,
    cancel_check: CancelCheck | None = None,
) -> tuple[str, str]:
    """
    Stream ChatOpenAI tokens into ai_progress.
    Returns (content, reasoning).

    首包前遇到瞬态错误（网关重启/限流）按统一重试层退避重试；已产出部分
    内容后的流中断不做重试（会重复输出），维持原有非流式兜底。
    cancel_check 每个 token 检查一次，返回 True 时抛 TurnCancelled 终止。
    """
    from backend.core.ai import usage_tracker

    content_parts: list[str] = []
    reasoning = ""
    attempts = 0
    while True:
        got_any = False
        try:
            for chunk in llm.stream(messages):
                got_any = True
                if cancel_check is not None and cancel_check():
                    raise TurnCancelled()
                um = getattr(chunk, "usage_metadata", None)
                if isinstance(um, dict):
                    usage_tracker.record(um)
                # content
                piece = getattr(chunk, "content", None)
                if piece:
                    if isinstance(piece, list):
                        text = "".join(
                            str(p.get("text", "")) if isinstance(p, dict) else str(p)
                            for p in piece
                        )
                    else:
                        text = str(piece)
                    if text:
                        content_parts.append(text)
                        emit_delta(
                            on_progress,
                            mode=mode,
                            conversation_id=conversation_id,
                            assistant_id=assistant_id,
                            text=text,
                        )
                # some models put reasoning in additional_kwargs
                ak = getattr(chunk, "additional_kwargs", None) or {}
                if isinstance(ak, dict):
                    r = ak.get("reasoning_content") or ak.get("reasoning")
                    if r:
                        reasoning = str(r)
                        emit_delta(
                            on_progress,
                            mode=mode,
                            conversation_id=conversation_id,
                            assistant_id=assistant_id,
                            text=str(r),
                            ev_type="reasoning",
                        )
            break
        except TurnCancelled:
            raise
        except Exception as exc:
            # 首包前的瞬态错误 → 退避重试；否则走非流式兜底
            if got_any or attempts >= DEFAULT_RETRIES or not is_transient_error(exc):
                _fallback_non_stream(
                    llm,
                    messages,
                    content_parts=content_parts,
                    on_progress=on_progress,
                    mode=mode,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                )
                break
            attempts += 1
            time.sleep(retry_delay(attempts - 1, base_delay=DEFAULT_BASE_DELAY))
    return "".join(content_parts), reasoning


def _fallback_non_stream(
    llm: Any,
    messages: list[Any],
    *,
    content_parts: list[str],
    on_progress: ProgressFn | None,
    mode: str,
    conversation_id: str,
    assistant_id: str,
) -> None:
    from backend.core.ai import usage_tracker

    msg = llm.invoke(messages)
    usage_tracker.record_message(msg)
    piece = getattr(msg, "content", "") or ""
    if isinstance(piece, list):
        text = "".join(
            str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in piece
        )
    else:
        text = str(piece)
    content_parts.append(text)
    emit_delta(
        on_progress,
        mode=mode,
        conversation_id=conversation_id,
        assistant_id=assistant_id,
        text=text,
        replace=True,
    )
