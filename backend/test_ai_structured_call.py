"""Tests for gateway-friendly structured invoke."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.lc import structured_call
from backend.core.ai.lc.structured_call import invoke_structured


class _Probe(BaseModel):
    ok: bool = Field(default=True)
    note: str = Field(default="")


def setup_function(_fn=None):
    structured_call._JSON_MODE_UNSUPPORTED = False


def test_invoke_structured_prefers_json_schema():
    calls: list[str | None] = []

    class FakeBound:
        def __init__(self, method):
            self.method = method

        def invoke(self, _messages):
            if self.method == "json_schema":
                return _Probe(ok=True, note="schema")
            raise RuntimeError(f"should not use {self.method}")

    class FakeLLM:
        def with_structured_output(self, schema, method="function_calling"):
            calls.append(method)
            return FakeBound(method)

    out = invoke_structured(FakeLLM(), _Probe, [("user", "x")])
    assert out.ok is True
    assert out.note == "schema"
    assert calls == ["json_schema"]


def test_invoke_structured_marks_json_mode_unsupported_and_continues():
    calls: list[str | None] = []

    class FakeBound:
        def __init__(self, method):
            self.method = method

        def invoke(self, _messages):
            if self.method == "json_schema":
                raise RuntimeError("temporary schema glitch")
            if self.method == "json_mode":
                raise RuntimeError(
                    "Error code: 400 - {'error': \"'response_format.type' "
                    "must be 'json_schema' or 'text'\"}"
                )
            return _Probe(ok=True, note="default")

    class FakeLLM:
        def with_structured_output(self, schema, method=None):
            calls.append(method)
            return FakeBound(method)

    out = invoke_structured(FakeLLM(), _Probe, [("user", "x")])
    assert out.note == "default"
    assert structured_call._JSON_MODE_UNSUPPORTED is True
    assert "json_mode" in calls


def test_invoke_structured_skips_json_mode_after_gateway_reject():
    structured_call._JSON_MODE_UNSUPPORTED = True
    calls: list[str | None] = []

    class FakeBound:
        def __init__(self, method):
            self.method = method

        def invoke(self, _messages):
            if self.method == "json_schema":
                return _Probe(ok=True, note="schema")
            raise RuntimeError(f"unexpected {self.method}")

    class FakeLLM:
        def with_structured_output(self, schema, method="function_calling"):
            calls.append(method)
            return FakeBound(method)

    out = invoke_structured(FakeLLM(), _Probe, [("user", "x")])
    assert out.note == "schema"
    assert "json_mode" not in calls


def test_invoke_structured_compact_retry_on_length_limit():
    class FakeBound:
        def invoke(self, messages):
            blob = " ".join(str(m) for m in messages)
            if "COMPACT" not in blob:
                raise RuntimeError(
                    "Could not parse response content as the length limit was reached"
                )
            return _Probe(ok=True, note="compact")

    class FakeLLM:
        def with_structured_output(self, schema, method="json_schema"):
            return FakeBound()

    out = invoke_structured(
        FakeLLM(),
        _Probe,
        [("user", "LONG CONTEXT")],
        compact_messages=[("user", "COMPACT")],
    )
    assert out.note == "compact"
