"""Tests for Flow AI draft builder, tool catalog, runtime, and FC client."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai import draft_builder
from backend.core.ai.tool_catalog import (
    DEFAULT_DENIED_BLOCKS,
    is_block_allowed,
    list_blocks,
    openai_tools,
)
from backend.core.ai.tool_runtime import ToolRuntime, assistant_tool_call_message
from backend.core.ai.providers.openai_compat import OpenAiCompatClient
from backend.core.ai.conversation_store import ConversationStore
from backend.core.ai.session_manager import SessionManager
from backend.core.ai.types import LlmTurn


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_openai_tools_catalog_shape():
    tools = openai_tools()
    names = {t["function"]["name"] for t in tools}
    assert "list_blocks" in names
    assert "draft_add_node" in names
    assert "locate_text_on_screen" in names
    assert "bind_point_to_node" in names
    assert len(tools) >= 10


def test_list_blocks_excludes_dangerous():
    blocks = list_blocks(allow_dangerous=False)
    types = {b["type"] for b in blocks}
    assert "delay" in types
    assert "click" in types
    assert "run_command" not in types
    assert "python_script" not in types
    assert "file_io" not in types
    assert is_block_allowed("run_command") is False
    for t in DEFAULT_DENIED_BLOCKS:
        assert t not in types


def test_draft_builder_add_connect_remove():
    draft = draft_builder.empty_draft()
    draft, a = draft_builder.add_node(draft, block_type="delay", params={"ms": 1000})
    draft, b = draft_builder.add_node(draft, block_type="type_text", params={"text": "hello"})
    draft_builder.connect(draft, from_id=a, to_id=b, edge="next")
    draft_builder.set_entry(draft, a)
    assert draft["entry"] == a
    assert draft["nodes"][a]["next"] == b

    summary = draft_builder.draft_summary(draft)
    assert summary["node_count"] == 2

    draft_builder.remove_node(draft, b)
    assert b not in draft["nodes"]
    assert draft["nodes"][a]["next"] is None


def test_params_need_coord_refs():
    assert set(draft_builder.params_need_coord_refs({"x": 100, "y": 200})) == {"x", "y"}
    assert draft_builder.params_need_coord_refs({"x": "{{n.x}}", "y": "{{n.y}}"}) == []
    assert draft_builder.params_need_coord_refs({"ms": 500}) == []


def test_tool_runtime_draft_orchestration():
    draft = draft_builder.empty_draft()
    artifacts = {"shots": {}, "points": {}}
    trace = []
    rt = ToolRuntime(strict_coords=False)

    r1 = rt.execute(
        "draft_add_node",
        {"type": "delay", "params": {"ms": 1000}, "node_id": "n_delay"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert r1["ok"] is True
    assert "n_delay" in draft["nodes"]

    r2 = rt.execute(
        "draft_add_node",
        {"type": "type_text", "params": {"text": "hello"}, "node_id": "n_type"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert r2["ok"] is True

    r3 = rt.execute(
        "draft_add_node",
        {
            "type": "click",
            "params": {"x": 100, "y": 200, "click_mode": "single"},
            "node_id": "n_click",
        },
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert r3["ok"] is True
    assert draft["nodes"]["n_click"].get("_ai_unverified_coords") is True

    rt.execute(
        "draft_connect",
        {"from_id": "n_delay", "to_id": "n_type", "edge": "next"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    rt.execute(
        "draft_connect",
        {"from_id": "n_type", "to_id": "n_click", "edge": "next"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    rt.execute(
        "draft_set_entry",
        {"node_id": "n_delay"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert draft["entry"] == "n_delay"
    assert draft["nodes"]["n_delay"]["next"] == "n_type"
    assert draft["nodes"]["n_type"]["next"] == "n_click"

    denied = rt.execute(
        "draft_add_node",
        {"type": "run_command", "params": {"command": "echo hi"}},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert denied["ok"] is False


def test_tool_runtime_strict_coords_reject():
    draft = draft_builder.empty_draft()
    artifacts = {"shots": {}, "points": {}}
    trace = []
    rt = ToolRuntime(strict_coords=True)
    r = rt.execute(
        "draft_add_node",
        {"type": "click", "params": {"x": 10, "y": 20}},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    assert r["ok"] is False
    assert "坐标" in (r.get("error") or "")


def test_tool_runtime_bind_point():
    draft = draft_builder.empty_draft()
    artifacts = {
        "shots": {},
        "points": {
            "pt_1": {
                "ref_id": "pt_1",
                "x": 50,
                "y": 60,
                "packed": {
                    "x": 50,
                    "y": 60,
                    "coordinate_mode": "screen_abs",
                    "point_norm": [0.1, 0.2],
                },
                "source": "ocr",
            }
        },
    }
    trace = []
    rt = ToolRuntime()
    rt.execute(
        "draft_add_node",
        {"type": "click", "params": {}, "node_id": "c1", "point_ref": "pt_1"},
        draft=draft,
        artifacts=artifacts,
        tool_trace=trace,
    )
    params = draft["nodes"]["c1"]["params"]
    assert params["x"] == 50
    assert params["y"] == 60
    assert params.get("_ai_point_ref") == "pt_1"
    assert not draft["nodes"]["c1"].get("_ai_unverified_coords")


def test_chat_parses_tool_calls():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "list_blocks",
                                "arguments": '{"category":"动作类"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    client = OpenAiCompatClient(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        http_client=mock_client,
    )
    tools = openai_tools()
    turn = client.chat([{"role": "user", "content": "hi"}], tools=tools)
    assert turn.content == ""
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0]["name"] == "list_blocks"
    assert turn.tool_calls[0]["arguments"]["category"] == "动作类"
    body = mock_client.post.call_args.kwargs["json"]
    assert "tools" in body
    assert body["tool_choice"] == "auto"


def test_session_tool_loop_mock_llm(tmp_path: Path, monkeypatch):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create(title="t")

    class FakeClient:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None, **kwargs):
            self.n += 1
            if self.n == 1:
                return LlmTurn(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "draft_add_node",
                            "arguments": {
                                "type": "delay",
                                "params": {"ms": 1000},
                                "node_id": "d1",
                            },
                            "raw": {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "draft_add_node",
                                    "arguments": json.dumps(
                                        {
                                            "type": "delay",
                                            "params": {"ms": 1000},
                                            "node_id": "d1",
                                        }
                                    ),
                                },
                            },
                        },
                        {
                            "id": "c2",
                            "name": "draft_add_node",
                            "arguments": {
                                "type": "type_text",
                                "params": {"text": "hello"},
                                "node_id": "t1",
                            },
                            "raw": {
                                "id": "c2",
                                "type": "function",
                                "function": {
                                    "name": "draft_add_node",
                                    "arguments": json.dumps(
                                        {
                                            "type": "type_text",
                                            "params": {"text": "hello"},
                                            "node_id": "t1",
                                        }
                                    ),
                                },
                            },
                        },
                    ],
                )
            if self.n == 2:
                return LlmTurn(
                    content="",
                    tool_calls=[
                        {
                            "id": "c3",
                            "name": "draft_connect",
                            "arguments": {
                                "from_id": "d1",
                                "to_id": "t1",
                                "edge": "next",
                            },
                            "raw": {
                                "id": "c3",
                                "type": "function",
                                "function": {
                                    "name": "draft_connect",
                                    "arguments": json.dumps(
                                        {
                                            "from_id": "d1",
                                            "to_id": "t1",
                                            "edge": "next",
                                        }
                                    ),
                                },
                            },
                        }
                    ],
                )
            return LlmTurn(content="已生成 delay → type_text 草稿，请确认。", tool_calls=[])

    mgr = SessionManager(store=store)
    fake = FakeClient()

    import backend.core.ai.session_manager as sm
    from backend.core.ai import config as ai_config

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        ai_config,
        "load_app_config",
        lambda: json.loads(cfg_file.read_text(encoding="utf-8") or "{}"),
    )
    monkeypatch.setattr(
        ai_config,
        "save_app_config",
        lambda cfg: cfg_file.write_text(json.dumps(cfg), encoding="utf-8"),
    )
    monkeypatch.setattr(sm, "create_llm_client", lambda cfg=None: fake)

    ai_config.set_ai_config(
        {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model": "gpt-test",
        }
    )

    res = mgr.chat(meta.id, "先等待 1 秒再输入 hello")
    assert res["ok"] is True, res
    nodes = {n["id"]: n for n in res["draft_summary"]["nodes"]}
    assert "d1" in nodes
    assert "t1" in nodes
    draft = store.get(meta.id)["draft"]
    assert draft["nodes"]["d1"]["next"] == "t1"
    assert "已生成" in res["assistant_message"]["content"]


def test_assistant_tool_call_message_shape():
    msg = assistant_tool_call_message(
        "",
        [{"id": "1", "name": "list_blocks", "arguments": {"category": "动作类"}}],
    )
    assert msg["role"] == "assistant"
    assert msg["tool_calls"][0]["function"]["name"] == "list_blocks"


def test_apply_draft_strips_markers(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create()
    draft = draft_builder.empty_draft()
    draft, nid = draft_builder.add_node(
        draft,
        block_type="click",
        params={"x": 1, "y": 2, "_ai_point_ref": "pt_x"},
        node_id="c1",
        extra={"_ai_unverified_coords": True},
    )
    store.save_session_state(meta.id, draft=draft, status="awaiting_confirm")
    mgr = SessionManager(store=store)
    res = mgr.apply_draft(meta.id, validate_fn=lambda f: None)
    assert res["ok"] is True
    node = res["flow"]["nodes"]["c1"]
    assert "_ai_unverified_coords" not in node
    assert "_ai_point_ref" not in node["params"]
    assert node["params"]["x"] == 1


def test_conversation_store_has_draft(tmp_path: Path):
    store = ConversationStore(root=tmp_path / "conversations")
    meta = store.create()
    data = store.get(meta.id)
    assert data is not None
    assert isinstance(data["draft"], dict)
    assert "nodes" in data["draft"]
    assert data["status"] == "idle"
