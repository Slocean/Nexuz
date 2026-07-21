"""Tests for AI conversation store persistence."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.conversation_store import ConversationStore
from backend.core.ai.types import ChatMessage


def test_create_list_get_rename_delete(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create(title="新对话", model="gpt-test")
    assert meta.id
    assert meta.title == "新对话"
    assert meta.model == "gpt-test"

    listed = store.list_conversations()
    assert len(listed) == 1
    assert listed[0].id == meta.id

    data = store.get(meta.id)
    assert data is not None
    assert data["meta"]["id"] == meta.id
    assert data["messages"] == []

    renamed = store.rename(meta.id, "问候")
    assert renamed is not None
    assert renamed.title == "问候"

    msgs = [
        ChatMessage(id="u1", role="user", content="你好", timestamp="t1"),
        ChatMessage(id="a1", role="assistant", content="你好！", timestamp="t2"),
    ]
    updated = store.append_messages(meta.id, msgs, title="你好", model="gpt-test")
    assert updated is not None
    assert updated.message_count == 2
    assert updated.title == "你好"

    data2 = store.get(meta.id)
    assert data2 is not None
    assert len(data2["messages"]) == 2
    assert data2["messages"][0]["content"] == "你好"

    assert store.delete(meta.id) is True
    assert store.get(meta.id) is None
    assert store.list_conversations() == []
    assert store.delete("missing") is False


def test_rejects_bad_id(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create()
    try:
        store.get("../etc")
        assert False, "expected ValueError"
    except ValueError:
        pass
    # still readable by real id
    assert store.get(meta.id) is not None
