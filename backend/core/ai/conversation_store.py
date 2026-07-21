"""Persist AI conversations under {data_dir}/ai/conversations/."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.ai.draft_builder import clone_flow, empty_draft
from backend.core.ai.types import ChatMessage, ConversationMeta
from backend.paths import get_data_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ai_conversations_dir(*, create: bool = True) -> Path:
    root = get_data_dir(create=create) / "ai" / "conversations"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _empty_artifacts() -> dict[str, Any]:
    return {"shots": {}, "points": {}}


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
        self._write_full(
            meta.id,
            messages=[],
            draft=empty_draft(),
            base_flow=None,
            artifacts=_empty_artifacts(),
            tool_trace=[],
            status="idle",
        )
        return meta

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        data = self._read_full(conversation_id)
        return {
            "meta": meta.to_dict(),
            "messages": [m.to_dict() for m in data["messages"]],
            "draft": data["draft"],
            "base_flow": data["base_flow"],
            "artifacts": data["artifacts"],
            "tool_trace": data["tool_trace"],
            "status": data["status"],
        }

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
        draft: dict[str, Any] | None = None,
        base_flow: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
        status: str | None = None,
        update_draft: bool = False,
        update_base_flow: bool = False,
        update_artifacts: bool = False,
        update_tool_trace: bool = False,
    ) -> ConversationMeta | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        data = self._read_full(conversation_id)
        existing = data["messages"]
        existing.extend(messages)

        new_draft = draft if update_draft and draft is not None else data["draft"]
        new_base = base_flow if update_base_flow else data["base_flow"]
        new_arts = artifacts if update_artifacts and artifacts is not None else data["artifacts"]
        new_trace = tool_trace if update_tool_trace and tool_trace is not None else data["tool_trace"]
        new_status = status if status is not None else data["status"]

        self._write_full(
            conversation_id,
            messages=existing,
            draft=new_draft,
            base_flow=new_base,
            artifacts=new_arts,
            tool_trace=new_trace,
            status=new_status,
        )

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

    def save_session_state(
        self,
        conversation_id: str,
        *,
        draft: dict[str, Any] | None = None,
        base_flow: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
        status: str | None = None,
        set_base_flow: bool = False,
    ) -> bool:
        self._validate_id(conversation_id)
        if self._find_meta(conversation_id) is None:
            return False
        data = self._read_full(conversation_id)
        self._write_full(
            conversation_id,
            messages=data["messages"],
            draft=draft if draft is not None else data["draft"],
            base_flow=base_flow if set_base_flow else data["base_flow"],
            artifacts=artifacts if artifacts is not None else data["artifacts"],
            tool_trace=tool_trace if tool_trace is not None else data["tool_trace"],
            status=status if status is not None else data["status"],
        )
        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["updated_at"] = _utc_now_iso()
                self._save_index(items)
                break
        return True

    def _find_meta(self, conversation_id: str) -> ConversationMeta | None:
        for item in self._load_index():
            if item.get("id") == conversation_id:
                return ConversationMeta.from_dict(item)
        return None

    def _read_full(self, conversation_id: str) -> dict[str, Any]:
        path = self._conv_path(conversation_id)
        if not path.is_file():
            return {
                "messages": [],
                "draft": empty_draft(),
                "base_flow": None,
                "artifacts": _empty_artifacts(),
                "tool_trace": [],
                "status": "idle",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "messages": [],
                "draft": empty_draft(),
                "base_flow": None,
                "artifacts": _empty_artifacts(),
                "tool_trace": [],
                "status": "idle",
            }
        if not isinstance(data, dict):
            data = {}
        raw_msgs = data.get("messages")
        messages = [
            ChatMessage.from_dict(m) for m in raw_msgs if isinstance(m, dict)
        ] if isinstance(raw_msgs, list) else []
        draft = data.get("draft")
        if not isinstance(draft, dict):
            draft = empty_draft()
        else:
            draft = clone_flow(draft)
        base_flow = data.get("base_flow") if isinstance(data.get("base_flow"), dict) else None
        artifacts = data.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = _empty_artifacts()
        else:
            artifacts = {
                "shots": artifacts.get("shots")
                if isinstance(artifacts.get("shots"), dict)
                else {},
                "points": artifacts.get("points")
                if isinstance(artifacts.get("points"), dict)
                else {},
            }
        tool_trace = data.get("tool_trace") if isinstance(data.get("tool_trace"), list) else []
        status = str(data.get("status") or "idle")
        return {
            "messages": messages,
            "draft": draft,
            "base_flow": base_flow,
            "artifacts": artifacts,
            "tool_trace": tool_trace,
            "status": status,
        }

    def _write_full(
        self,
        conversation_id: str,
        *,
        messages: list[ChatMessage],
        draft: dict[str, Any],
        base_flow: dict[str, Any] | None,
        artifacts: dict[str, Any],
        tool_trace: list[dict[str, Any]],
        status: str,
    ) -> None:
        path = self._conv_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist shot data_urls (needed for UI preview); keep as-is
        payload = {
            "id": conversation_id,
            "messages": [m.to_dict() for m in messages],
            "draft": draft,
            "base_flow": base_flow,
            "artifacts": artifacts,
            "tool_trace": tool_trace,
            "status": status,
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
