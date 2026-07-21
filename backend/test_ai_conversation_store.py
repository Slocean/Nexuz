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
    meta = store.create(title="新对话", model="gpt-test", kind="chat")
    assert meta.id
    assert meta.title == "新对话"
    assert meta.model == "gpt-test"
    assert meta.kind == "chat"

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


def test_kind_isolates_chat_and_flow(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    chat = store.create(title="聊", kind="chat")
    flow = store.create(title="排", kind="flow")
    assert chat.kind == "chat"
    assert flow.kind == "flow"
    assert {m.id for m in store.list_conversations(kind="chat")} == {chat.id}
    assert {m.id for m in store.list_conversations(kind="flow")} == {flow.id}
    assert len(store.list_conversations()) == 2


def test_orchestration_sidecar_and_apply_payload(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create(title="排", kind="flow")
    draft = {
        "flow_id": "f1",
        "name": "草稿",
        "entry": "n1",
        "nodes": {
            "n1": {"id": "n1", "type": "click", "params": {"x": 1, "y": 2}},
        },
    }
    process = [{"kind": "tool", "name": "add_node", "ok": True}]
    card = {
        "summary": {"node_count": 1, "entry": "n1", "nodes": [{"id": "n1", "type": "click"}]},
        "diff": {"added": [{"id": "n1", "type": "click"}], "removed": [], "changed": []},
        "warnings": [],
        "tool_trace": [{"name": "add_node", "ok": True}],
        "points": [],
        "shot": {
            "shot_id": "s1",
            "width": 10,
            "height": 10,
            "data_url": "data:image/png;base64,aaaa",
        },
        "status": "awaiting_confirm",
    }
    arts = {
        "shots": {
            "s1": {
                "shot_id": "s1",
                "width": 10,
                "height": 10,
                "data_url": "data:image/png;base64,aaaa",
                "created_at": 1,
            }
        },
        "points": {},
    }
    lean = store.save_orchestration_result(
        meta.id,
        "msg-a1",
        draft=draft,
        process=process,
        card=card,
        artifacts=arts,
    )
    assert lean["has_result"] is True
    assert lean["result_id"] == "msg-a1"
    assert "data_url" not in (lean.get("shot") or {})

    # Main conversation file must stay lean (no draft blob on message)
    asst = ChatMessage(
        id="msg-a1",
        role="assistant",
        content="好了",
        timestamp="t",
        process=process,
        orchestration=lean,
    )
    store.append_messages(meta.id, [asst], update_draft=True, draft=draft)

    data = store.get(meta.id)
    assert data is not None
    msg = data["messages"][0]
    assert msg["orchestration"]["result_id"] == "msg-a1"
    assert "draft" not in msg["orchestration"]
    assert "data_url" not in (msg["orchestration"].get("shot") or {})

    orch = store.get_orchestration_result(meta.id, "msg-a1", include_shot_image=True)
    assert orch is not None
    assert orch["draft"]["nodes"]["n1"]["type"] == "click"
    assert orch["process"] == process
    assert orch["shot"]["data_url"].startswith("data:image")

    # Delete removes sidecar dir
    assert (tmp_path / "conversations" / meta.id / "orch" / "msg-a1.json").is_file()
    assert store.delete(meta.id) is True
    assert not (tmp_path / "conversations" / meta.id).exists()


def test_rejects_bad_id(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create()
    try:
        store.get("../etc")
    except ValueError:
        pass
    else:
        assert False, "expected ValueError"
    assert store.get(meta.id) is not None
