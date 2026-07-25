"""LangGraph flow graph routing / repair smoke tests (no live LLM)."""

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
from backend.core.ai.lc.structured import FlowSpec, PlanStep
from backend.core.ai.types import AiConfig


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_flow_graph_builds_delay_type(monkeypatch):
    class FakeStructured:
        def invoke(self, _messages):
            return FlowSpec(
                intent_summary="demo",
                steps=[
                    PlanStep(action="delay", params={"ms": 500}),
                    PlanStep(action="type_text", params={"text": "hi"}),
                ],
            )

    class FakeLLM:
        def with_structured_output(self, _schema):
            return FakeStructured()

        def stream(self, _messages):
            yield AIMessage(content="编排完成，请确认。")

        def invoke(self, _messages):
            return AIMessage(content="编排完成，请确认。")

    import backend.core.ai.graphs.flow_graph as fg

    monkeypatch.setattr(fg, "create_chat_model", lambda *a, **k: FakeLLM())
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
