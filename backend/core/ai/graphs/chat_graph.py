"""LangGraph chat graph: history → LLM → reply (no tools)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from backend.core.ai.checkpointer import get_checkpointer, thread_config
from backend.core.ai.graphs.state import ChatGraphState
from backend.core.ai.graphs.streaming import emit_delta, stream_chat_model
from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.lc.prompts import CHAT_SYSTEM
from backend.core.ai.types import AiConfig

ProgressFn = Callable[[dict[str, Any]], None]


def _history_to_lc_messages(history: list[dict[str, Any]]) -> list[Any]:
    out: list[Any] = []
    for m in history:
        role = m.get("role")
        content = str(m.get("content") or "")
        if not content:
            continue
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        elif role == "system":
            out.append(SystemMessage(content=content))
    return out


def build_chat_graph(*, checkpointer: Any | None = None):
    """Compile chat StateGraph. Checkpoint optional (facade often runs without)."""

    def llm_node(state: ChatGraphState) -> dict[str, Any]:
        # Placeholder — real streaming done in run_chat_graph for progress bridging
        return {"reply": state.get("reply") or ""}

    g = StateGraph(ChatGraphState)
    g.add_node("llm", llm_node)
    g.add_edge(START, "llm")
    g.add_edge("llm", END)
    return g.compile(checkpointer=checkpointer)


def run_chat_graph(
    *,
    conversation_id: str,
    user_text: str,
    history: list[dict[str, Any]],
    cfg: AiConfig | None = None,
    on_progress: ProgressFn | None = None,
    assistant_id: str = "",
    use_checkpoint: bool = True,
) -> dict[str, Any]:
    """
    Execute chat turn with LangChain ChatOpenAI streaming.
    Optionally records a checkpoint under thread_id=conversation_id.
    """
    messages = [SystemMessage(content=CHAT_SYSTEM)]
    messages.extend(_history_to_lc_messages(history))
    messages.append(HumanMessage(content=user_text))

    from backend.core.ai import cancel as turn_cancel

    llm = create_chat_model(cfg, streaming=True)
    content, reasoning = stream_chat_model(
        llm,
        messages,
        on_progress=on_progress,
        mode="chat",
        conversation_id=conversation_id,
        assistant_id=assistant_id,
        cancel_check=lambda: turn_cancel.is_cancelled(conversation_id),
    )
    reply = (content or "").strip() or "好的。"

    if use_checkpoint:
        try:
            cp = get_checkpointer()
            if cp is not None:
                graph = build_chat_graph(checkpointer=cp)
                graph.invoke(
                    {
                        "messages": messages + [AIMessage(content=reply)],
                        "input": user_text,
                        "reply": reply,
                    },
                    config=thread_config(conversation_id),
                )
        except Exception:
            # checkpoint 形同记录用途，失败不阻塞对话；但静默会让跨轮恢复
            # 失效难以察觉（本图 checkpoint 只写不读，见 run_chat_graph）。
            logging.getLogger(__name__).warning("chat checkpoint 写入失败", exc_info=True)

    process: list[dict[str, Any]] = []
    if reasoning:
        process.append({"kind": "think", "label": "思考", "text": reasoning.strip()})

    return {"ok": True, "reply": reply, "reasoning": reasoning, "process": process}
