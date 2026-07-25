"""LangGraph step-wise flow graph smoke tests (no live LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai.draft_builder import empty_draft
from backend.core.ai.graphs.flow_graph import run_flow_graph
from backend.core.ai.lc.structured import (
    GapCheckResult,
    IntentUnderstanding,
    OutlineStep,
    PlanOutline,
)
from backend.core.ai.types import AiConfig


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def _fake_llm_for_delay_type():
    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, _messages):
            if self.schema is IntentUnderstanding:
                return IntentUnderstanding(
                    intent="等待后输入 hi",
                    known_slots={"message": "hi"},
                    ambiguities=[],
                )
            if self.schema is PlanOutline:
                return PlanOutline(
                    summary="delay then type",
                    steps=[
                        OutlineStep(
                            id="s1",
                            goal="等待",
                            block_hint="delay",
                            needs_sense="none",
                            params={"ms": 500},
                        ),
                        OutlineStep(
                            id="s2",
                            goal="输入 hi",
                            block_hint="type_text",
                            needs_sense="none",
                            params={"text": "hi"},
                        ),
                    ],
                )
            if self.schema is GapCheckResult:
                return GapCheckResult(complete=True, missing=[], hints=[])
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructured(schema)

        def bind_tools(self, _tools):
            return self

        def stream(self, _messages):
            yield AIMessage(content="草稿 delay → type_text，请确认。")

        def invoke(self, _messages):
            return AIMessage(content="草稿 delay → type_text，请确认。")

    return FakeLLM()


def test_flow_graph_builds_delay_type(monkeypatch):
    import backend.core.ai.graphs.flow_graph as fg

    monkeypatch.setattr(fg, "create_chat_model", lambda *a, **k: _fake_llm_for_delay_type())
    monkeypatch.setattr(fg, "get_checkpointer", lambda: None)

    cfg = AiConfig(base_url="https://example.com/v1", api_key="k", model="m")
    out = run_flow_graph(
        conversation_id="test-thread",
        user_text="等待后输入 hi",
        draft=empty_draft(),
        cfg=cfg,
        use_checkpoint=False,
    )
    assert out["ok"] is True
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert "delay" in types and "type_text" in types
    assert out["reply"]
    assert any(p.get("node") == "validate" for p in out["process"])
    assert any(p.get("node") == "understand" for p in out["process"])
    assert any(p.get("node") == "plan_outline" for p in out["process"])
    assert any(p.get("node") == "build_loop" for p in out["process"])
    assert out["draft"].get("nodes")
    # empty-draft honesty: with nodes, reply should not claim empty
    assert "草稿为空" not in (out["reply"] or "")


def test_flow_graph_clarify_then_resume(monkeypatch):
    """First turn asks clarify; resume with answer continues to outline/build."""
    import backend.core.ai.graphs.flow_graph as fg

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            blob = " ".join(str(getattr(m, "content", m)) for m in messages)
            if self.schema is IntentUnderstanding:
                if "张三" in blob or "联系人甲" in blob:
                    return IntentUnderstanding(
                        intent="发消息",
                        known_slots={
                            "contact": "张三",
                            "message": "你好",
                            "window_title": "微信",
                        },
                        ambiguities=[],
                    )
                return IntentUnderstanding(
                    intent="发消息",
                    known_slots={"message": "你好", "window_title": "微信"},
                    ambiguities=[
                        {
                            "id": "contact",
                            "prompt": "发给哪位联系人？",
                            "choices": [],
                            "allow_free_text": True,
                        }
                    ],
                )
            if self.schema is PlanOutline:
                return PlanOutline(
                    summary="wechat once",
                    steps=[
                        OutlineStep(
                            id="s1",
                            goal="激活微信",
                            block_hint="window_activate",
                            params={"title": "微信"},
                        ),
                        OutlineStep(
                            id="s2",
                            goal="点联系人",
                            block_hint="ocr_click",
                            needs_sense="ocr",
                            match_text="张三",
                        ),
                        OutlineStep(
                            id="s3",
                            goal="输入",
                            block_hint="type_text",
                            params={"text": "你好"},
                        ),
                    ],
                )
            if self.schema is GapCheckResult:
                return GapCheckResult(complete=True)
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructured(schema)

        def bind_tools(self, _tools):
            return self

        def stream(self, _messages):
            yield AIMessage(content="ok")

        def invoke(self, _messages):
            return AIMessage(content="ok")

    monkeypatch.setattr(fg, "create_chat_model", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(fg, "get_checkpointer", lambda: None)
    cfg = AiConfig(base_url="https://example.com/v1", api_key="k", model="m")

    first = run_flow_graph(
        conversation_id="clarify-thread",
        user_text="用微信发消息你好",
        draft=empty_draft(),
        cfg=cfg,
        use_checkpoint=False,
    )
    assert first["clarify_questions"]
    assert not (first["draft"].get("nodes") or {})
    assert "补充" in (first["reply"] or "") or "澄清" in str(first.get("process"))

    second = run_flow_graph(
        conversation_id="clarify-thread",
        user_text="张三",
        draft=empty_draft(),
        cfg=cfg,
        use_checkpoint=False,
        resume_clarify=True,
        pending_clarify=first["clarify_questions"],
        known_slots=dict(first.get("known_slots") or {}),
        intent=str(first.get("intent") or ""),
    )
    assert not second.get("clarify_questions")
    types = [n["type"] for n in (second["draft"].get("nodes") or {}).values()]
    assert "window_activate" in types
    assert "type_text" in types
    assert (second.get("known_slots") or {}).get("contact") == "张三"


def test_summarize_empty_draft_honest(monkeypatch):
    import backend.core.ai.graphs.flow_graph as fg

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, _messages):
            if self.schema is IntentUnderstanding:
                return IntentUnderstanding(intent="空", known_slots={}, ambiguities=[])
            if self.schema is PlanOutline:
                return PlanOutline(summary="empty", steps=[])
            if self.schema is GapCheckResult:
                return GapCheckResult(complete=True)
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructured(schema)

        def bind_tools(self, _tools):
            return self

        def stream(self, _messages):
            yield AIMessage(content="已准备好，请应用到画布")

        def invoke(self, _messages):
            return AIMessage(content="已准备好，请应用到画布")

    monkeypatch.setattr(fg, "create_chat_model", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(fg, "get_checkpointer", lambda: None)
    cfg = AiConfig(base_url="https://example.com/v1", api_key="k", model="m")
    out = run_flow_graph(
        conversation_id="empty-thread",
        user_text="随便",
        draft=empty_draft(),
        cfg=cfg,
        use_checkpoint=False,
    )
    reply = out["reply"] or ""
    assert "已准备好" not in reply
    assert "空" in reply or "0" in reply or "没有生成" in reply
