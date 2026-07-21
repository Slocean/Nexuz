"""Persist AI conversations under {data_dir}/ai/conversations/."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.ai.types import ChatMessage, ConversationMeta
from backend.paths import get_data_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ai_conversations_dir(*, create: bool = True) -> Path:
    root = get_data_dir(create=create) / "ai" / "conversations"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


class ConversationStore:
    def __init__(self, root: Path | None = None):
        self._root = root

    @property
    def root(self) -> Path:
        if self._root is not None:
            return self._root
        return ai_conversations_dir(create=True)

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _conv_path(self, conversation_id: str) -> Path:
        safe = self._validate_id(conversation_id)
        return self.root / f"{safe}.json"

    @staticmethod
    def _validate_id(conversation_id: str) -> str:
        safe = (conversation_id or "").strip()
        if not safe or "/" in safe or "\\" in safe or ".." in safe:
            raise ValueError("无效的 conversation_id")
        return safe

    def _load_index(self) -> list[dict[str, Any]]:
        path = self._index_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, dict) and isinstance(data.get("conversations"), list):
            return [c for c in data["conversations"] if isinstance(c, dict)]
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
        return []

    def _save_index(self, items: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"conversations": items}
        self._index_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_conversations(self) -> list[ConversationMeta]:
        items = self._load_index()
        metas = [ConversationMeta.from_dict(i) for i in items if i.get("id")]
        metas.sort(key=lambda m: m.updated_at or m.created_at, reverse=True)
        return metas

    def create(self, *, title: str = "新对话", model: str = "") -> ConversationMeta:
        now = _utc_now_iso()
        meta = ConversationMeta(
            id=str(uuid.uuid4()),
            title=(title or "新对话").strip() or "新对话",
            created_at=now,
            updated_at=now,
            model=model or "",
            message_count=0,
        )
        items = self._load_index()
        items.insert(0, meta.to_dict())
        self._save_index(items)
        self._write_conversation(meta.id, messages=[])
        return meta

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        messages = self._read_messages(conversation_id)
        return {"meta": meta.to_dict(), "messages": [m.to_dict() for m in messages]}

    def rename(self, conversation_id: str, title: str) -> ConversationMeta | None:
        self._validate_id(conversation_id)
        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["title"] = (title or "").strip() or item.get("title") or "新对话"
                item["updated_at"] = _utc_now_iso()
                self._save_index(items)
                return ConversationMeta.from_dict(item)
        return None

    def delete(self, conversation_id: str) -> bool:
        self._validate_id(conversation_id)
        items = self._load_index()
        new_items = [i for i in items if i.get("id") != conversation_id]
        if len(new_items) == len(items):
            return False
        self._save_index(new_items)
        path = self._conv_path(conversation_id)
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        return True

    def append_messages(
        self,
        conversation_id: str,
        messages: list[ChatMessage],
        *,
        title: str | None = None,
        model: str | None = None,
    ) -> ConversationMeta | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        existing = self._read_messages(conversation_id)
        existing.extend(messages)
        self._write_conversation(conversation_id, existing)

        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["updated_at"] = _utc_now_iso()
                item["message_count"] = len(existing)
                if title:
                    item["title"] = title
                if model is not None:
                    item["model"] = model
                self._save_index(items)
                return ConversationMeta.from_dict(item)
        return meta

    def _find_meta(self, conversation_id: str) -> ConversationMeta | None:
        for item in self._load_index():
            if item.get("id") == conversation_id:
                return ConversationMeta.from_dict(item)
        return None

    def _read_messages(self, conversation_id: str) -> list[ChatMessage]:
        path = self._conv_path(conversation_id)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw_msgs = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(raw_msgs, list):
            return []
        return [ChatMessage.from_dict(m) for m in raw_msgs if isinstance(m, dict)]

    def _write_conversation(self, conversation_id: str, messages: list[ChatMessage]) -> None:
        path = self._conv_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": conversation_id,
            "messages": [m.to_dict() for m in messages],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


def reset_conversation_store_for_tests(store: ConversationStore | None = None) -> None:
    global _store
    _store = store
