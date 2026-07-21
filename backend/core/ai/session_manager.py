"""Orchestrate chat: load history, call LLM, persist turns."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.core.ai.config import get_ai_config
from backend.core.ai.conversation_store import ConversationStore, get_conversation_store
from backend.core.ai.llm_client import create_llm_client
from backend.core.ai.types import ChatMessage, LlmError

SYSTEM_PROMPT = (
    "你是 Nexuz 桌面自动化助手。当前阶段仅支持普通多轮对话；"
    "请用简洁中文回答用户问题。后续版本将支持流程编排。"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _title_from_message(text: str, *, max_len: int = 36) -> str:
    t = " ".join((text or "").strip().split())
    if not t:
        return "新对话"
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


class SessionManager:
    def __init__(self, store: ConversationStore | None = None):
        self._store = store or get_conversation_store()

    def list_conversations(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self._store.list_conversations()]

    def create_conversation(self, *, title: str = "新对话") -> dict[str, Any]:
        cfg = get_ai_config()
        meta = self._store.create(title=title or "新对话", model=cfg.model)
        return meta.to_dict()

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._store.get(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any] | None:
        meta = self._store.rename(conversation_id, title)
        return meta.to_dict() if meta else None

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._store.delete(conversation_id)

    def test_connection(self) -> dict[str, Any]:
        cfg = get_ai_config()
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}
        try:
            client = create_llm_client(cfg)
            turn = client.chat(
                [
                    {"role": "system", "content": "Reply with exactly: ok"},
                    {"role": "user", "content": "ping"},
                ],
            )
            return {
                "ok": True,
                "model": cfg.model,
                "reply_preview": (turn.content or "")[:200],
            }
        except LlmError as exc:
            return {"ok": False, "error": exc.message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def chat(self, conversation_id: str, message: str) -> dict[str, Any]:
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "消息不能为空"}

        cfg = get_ai_config()
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}

        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}

        now = _utc_now_iso()
        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=text,
            timestamp=now,
        )

        history = conv.get("messages") or []
        llm_messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in history:
            role = m.get("role")
            if role in ("user", "assistant", "system") and m.get("content"):
                llm_messages.append({"role": role, "content": str(m["content"])})
        llm_messages.append({"role": "user", "content": text})

        try:
            client = create_llm_client(cfg)
            turn = client.chat(llm_messages)
        except LlmError as exc:
            return {"ok": False, "error": exc.message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        assistant_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=turn.content or "",
            timestamp=_utc_now_iso(),
        )

        meta_raw = conv.get("meta") or {}
        new_title = None
        # Auto-title on first user message
        if int(meta_raw.get("message_count") or 0) == 0:
            new_title = _title_from_message(text)

        updated = self._store.append_messages(
            conversation_id,
            [user_msg, assistant_msg],
            title=new_title,
            model=cfg.model,
        )
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "user_message": user_msg.to_dict(),
            "assistant_message": assistant_msg.to_dict(),
            "meta": updated.to_dict() if updated else meta_raw,
            "usage": turn.usage,
        }


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def reset_session_manager_for_tests(manager: SessionManager | None = None) -> None:
    global _manager
    _manager = manager
