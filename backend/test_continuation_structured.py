"""Continuation engine for truncated structured output."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.graphs.agent_ir import UnderstandIR
from backend.core.ai.token_scheduler.continuation import build_continuation_messages
from backend.core.ai.token_scheduler.generate import guarded_structured_invoke
from backend.core.ai.types import AiConfig


def test_build_continuation_messages_appends_hint():
    msgs = [("system", "sys"), ("user", "hi")]
    out = build_continuation_messages(msgs, partial_text='{"a":')
    assert len(out) == 3
    assert "截断" in str(out[-1].content)


def test_guarded_continue_after_raise_budget(monkeypatch):
    import backend.core.ai.token_scheduler.generate as gen

    calls: list[int] = []

    class FakeLLM:
        def __init__(self, max_tokens: int):
            self.max_tokens = int(max_tokens or 0)

        def with_structured_output(self, schema, **_kwargs):
            parent = self

            class Bound:
                def invoke(self, messages):
                    calls.append(parent.max_tokens)
                    text = " ".join(str(getattr(m, "content", m)) for m in messages)
                    # Fail until continuation hint present AND high budget
                    if "截断" not in text:
                        raise RuntimeError(
                            "Could not parse response content as the length limit was reached"
                        )
                    return UnderstandIR(
                        intent_tag="other", slots={"message": "ok"}, missing=[]
                    )

            return Bound()

    monkeypatch.setattr(gen, "create_chat_model", lambda _c, **kw: FakeLLM(kw.get("max_tokens") or 0))

    cfg = AiConfig(
        base_url="https://api.moonshot.cn/v1",
        api_key="k",
        model="kimi-k2.5",
    )
    out = guarded_structured_invoke(
        cfg,
        "understand",
        UnderstandIR,
        [("user", "ping")],
        max_continues=2,
    )
    assert getattr(out, "slots", {}).get("message") == "ok"
    # first attempt + raise-budget attempt + at least one continue
    assert len(calls) >= 3
    assert max(calls) >= 4096
