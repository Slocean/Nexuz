"""LangGraph step-wise flow graph smoke tests (compact IR, no live LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai.draft_builder import empty_draft
from backend.core.ai.graphs.agent_ir import IrStep, PlanIR, UnderstandIR
from backend.core.ai.graphs.flow_graph import run_flow_graph
from backend.core.ai.types import AiConfig


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


@pytest.fixture(autouse=True)
def _reset_native_tools_flag():
    import backend.core.ai.graphs.flow_graph as fg

    fg._NATIVE_TOOLS_UNAVAILABLE = False
    yield
    fg._NATIVE_TOOLS_UNAVAILABLE = False


def _fake_llm_for_delay_type():
    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, _messages):
            if self.schema is UnderstandIR:
                return UnderstandIR(
                    intent_tag="type_text",
                    slots={"message": "hi"},
                    missing=[],
                )
            if self.schema is PlanIR:
                return PlanIR(
                    steps=[
                        IrStep(op="wait", a={"ms": "500"}),
                        IrStep(op="type", a={"text": "hi"}),
                    ]
                )
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema, **_kwargs):
            return FakeStructured(schema)

        def bind_tools(self, _tools):
            raise AssertionError("compile_ir should build draft without tools")

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
    assert any(p.get("node") == "build_loop" for p in out["process"])
    assert out.get("plan_ir", {}).get("steps")
    assert "草稿为空" not in (out["reply"] or "")
    # IR compile path — no tool patch needed
    assert any(
        "IR" in str(p.get("text") or "") or p.get("label") in ("落图", "逐步落图")
        for p in out["process"]
    )


def test_flow_graph_clarify_then_resume(monkeypatch):
    import backend.core.ai.graphs.flow_graph as fg

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            blob = " ".join(str(getattr(m, "content", m)) for m in messages)
            if self.schema is UnderstandIR:
                if "张三" in blob or "联系人甲" in blob:
                    return UnderstandIR(
                        intent_tag="send_message",
                        slots={
                            "contact": "张三",
                            "message": "你好",
                            "window_title": "微信",
                        },
                        missing=[],
                    )
                return UnderstandIR(
                    intent_tag="send_message",
                    slots={"message": "你好", "window_title": "微信"},
                    missing=["contact"],
                )
            if self.schema is PlanIR:
                return PlanIR(steps=[IrStep(op="send_im", a={})])
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema, **_kwargs):
            return FakeStructured(schema)

        def bind_tools(self, _tools):
            raise AssertionError("should not need tools")

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
            if self.schema is UnderstandIR:
                return UnderstandIR(intent_tag="other", slots={}, missing=[])
            if self.schema is PlanIR:
                return PlanIR(steps=[])
            return self.schema()

    class FakeLLM:
        def with_structured_output(self, schema, **_kwargs):
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


def test_send_utterance_compiles_via_ir(monkeypatch):
    """Full send utterance → IR compile produces nodes even if LLM fails."""
    import backend.core.ai.graphs.flow_graph as fg

    class BoomLLM:
        def with_structured_output(self, schema, **_kwargs):
            raise RuntimeError("length limit was reached")

        def bind_tools(self, _tools):
            raise AssertionError("compile should not need tools")

        def stream(self, _messages):
            yield AIMessage(content="已生成发送草稿")

        def invoke(self, _messages):
            return AIMessage(content="已生成发送草稿")

    monkeypatch.setattr(fg, "create_chat_model", lambda *a, **k: BoomLLM())
    monkeypatch.setattr(fg, "get_checkpointer", lambda: None)
    cfg = AiConfig(base_url="https://example.com/v1", api_key="k", model="m")
    out = run_flow_graph(
        conversation_id="send-ir",
        user_text="打开微信给文件传输助手给他发送：你好",
        draft=empty_draft(),
        cfg=cfg,
        use_checkpoint=False,
    )
    assert out["ok"] is True
    assert (out.get("known_slots") or {}).get("contact") == "文件传输助手"
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert "window_activate" in types and "type_text" in types
    assert any(p.get("label") == "落图" for p in out["process"])


def test_structured_with_budget_retries_higher_max_tokens(monkeypatch):
    """First call hits length limit → retry with higher max_tokens succeeds."""
    import backend.core.ai.graphs.flow_graph as fg

    calls: list[int] = []

    class FakeLLM:
        def __init__(self, max_tokens: int):
            self.max_tokens = int(max_tokens or 0)

        def with_structured_output(self, schema, **_kwargs):
            parent = self

            class Bound:
                def invoke(self, _messages):
                    calls.append(parent.max_tokens)
                    # First budget for kimi understand is 4096; retry lifts to 8192
                    if parent.max_tokens < 5000:
                        raise RuntimeError(
                            "Could not parse response content as the length limit was reached"
                        )
                    return UnderstandIR(intent_tag="other", slots={"message": "x"}, missing=[])

            return Bound()

    def fake_create(_cfg, **kwargs):
        return FakeLLM(kwargs.get("max_tokens") or 0)

    monkeypatch.setattr(fg, "create_chat_model", fake_create)
    cfg = AiConfig(
        base_url="https://api.moonshot.cn/v1",
        api_key="k",
        model="kimi-k2.5",
    )
    out = fg._structured_with_budget(
        cfg,
        "understand",
        UnderstandIR,
        [("user", "ping")],
    )
    assert getattr(out, "slots", {}).get("message") == "x"
    assert calls[0] == 4096
    assert calls[1] == 8192
