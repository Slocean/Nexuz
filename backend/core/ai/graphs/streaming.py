"""Map LangGraph / LangChain stream events → Nexuz ai_progress payloads."""

from __future__ import annotations

from typing import Any, Callable

ProgressFn = Callable[[dict[str, Any]], None]


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
) -> tuple[str, str]:
    """
    Stream ChatOpenAI tokens into ai_progress.
    Returns (content, reasoning).
    """
    content_parts: list[str] = []
    reasoning = ""
    try:
        for chunk in llm.stream(messages):
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
    except Exception:
        # fallback non-stream
        msg = llm.invoke(messages)
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
    return "".join(content_parts), reasoning
