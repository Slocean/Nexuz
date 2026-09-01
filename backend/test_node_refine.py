"""node_refine（参数级 AI 修正）与 interpreter ai_refine hook。"""

from __future__ import annotations

import pytest

from backend.core.ai import node_refine
from backend.core.ai.node_refine import RefinedNodeParams, refine_node_params
from backend.core.ai.types import AiConfig
from backend.core.interpreter import FlowInterpreter
from backend.core.registry import BLOCK_REGISTRY, register_block


@pytest.fixture
def probe_block():
    seen: list[dict] = []
    schema = {
        "type": "fake_probe",
        "label": "探针",
        "category": "识别类",
        "inputs": [
            {"name": "text", "type": "string", "label": "文本", "required": True},
        ],
        "outputs": [{"name": "got", "type": "string"}],
    }

    def handler(params, context, **kwargs):
        seen.append(dict(params))
        return {"got": str(params.get("text"))}

    register_block(schema, handler)
    yield seen
    BLOCK_REGISTRY.pop("fake_probe", None)


def _cfg(enabled=True, base_url="https://api.example.com/v1"):
    return AiConfig(enabled=enabled, base_url=base_url, model="test-model")


def test_refine_disabled_without_ai(probe_block):
    assert refine_node_params(
        "fake_probe", {"text": "x"}, {}, cfg=_cfg(enabled=False)
    ) is None
    assert refine_node_params(
        "fake_probe", {"text": "x"}, {}, cfg=_cfg(base_url="")
    ) is None


def test_refine_unknown_block(probe_block):
    assert refine_node_params(
        "no_such", {"text": "x"}, {}, cfg=_cfg()
    ) is None


def test_refine_applies_valid_result(probe_block):
    def fake_invoke(cfg, profile, schema, messages, **kwargs):
        assert profile == "node_refine"
        assert kwargs.get("use_cache") is None or kwargs.get("use_cache") is not False
        return RefinedNodeParams(params={"text": "修正后"}, reason="依据 OCR")

    out = refine_node_params(
        "fake_probe",
        {"text": "原始"},
        {"prev.text": "修正后"},
        cfg=_cfg(),
        invoke_fn=fake_invoke,
    )
    assert out is not None
    refined, reason = out
    assert refined == {"text": "修正后"}
    assert reason == "依据 OCR"


def test_refine_noop_when_unchanged(probe_block):
    def fake_invoke(cfg, profile, schema, messages, **kwargs):
        return RefinedNodeParams(params={"text": "原始"})

    assert (
        refine_node_params(
            "fake_probe", {"text": "原始"}, {}, cfg=_cfg(), invoke_fn=fake_invoke
        )
        is None
    )


def test_refine_rejects_invalid_params(probe_block):
    def fake_invoke(cfg, profile, schema, messages, **kwargs):
        return RefinedNodeParams(params={"other": 1})  # 丢掉必填 text

    assert (
        refine_node_params(
            "fake_probe", {"text": "原始"}, {}, cfg=_cfg(), invoke_fn=fake_invoke
        )
        is None
    )


def test_refine_swallows_llm_failure(probe_block):
    def fake_invoke(cfg, profile, schema, messages, **kwargs):
        raise RuntimeError("boom")

    assert (
        refine_node_params(
            "fake_probe", {"text": "原始"}, {}, cfg=_cfg(), invoke_fn=fake_invoke
        )
        is None
    )


def test_interpreter_applies_refined_params(probe_block, monkeypatch):
    events = []

    def fake_refine(block_type, params, context):
        assert block_type == "fake_probe"
        return {"text": "AI 决定"}, "命中 OCR 文本"

    monkeypatch.setattr(node_refine, "refine_node_params", fake_refine)
    flow = {
        "entry": "n1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "n1": {
                "type": "fake_probe",
                "ai_refine": True,
                "params": {"text": "原始"},
            }
        },
    }
    context = FlowInterpreter(
        lambda event, payload: events.append((event, payload))
    )._execute(flow)
    assert probe_block[0] == {"text": "AI 决定"}
    assert context["n1.got"] == "AI 决定"
    logs = [p for e, p in events if e == "log" and "AI 参数修正" in str(p.get("message"))]
    assert logs and "text" in str(logs[0].get("detail"))


def test_interpreter_skips_refine_without_flag(probe_block, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("不应调用 refine")

    monkeypatch.setattr(node_refine, "refine_node_params", unexpected)
    flow = {
        "entry": "n1",
        "execution_policy": {"mode": "safe"},
        "nodes": {"n1": {"type": "fake_probe", "params": {"text": "原始"}}},
    }
    FlowInterpreter()._execute(flow)
    assert probe_block[0] == {"text": "原始"}


def test_interpreter_falls_back_on_refine_error(probe_block, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(node_refine, "refine_node_params", boom)
    events = []
    flow = {
        "entry": "n1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "n1": {
                "type": "fake_probe",
                "ai_refine": True,
                "params": {"text": "原始"},
            }
        },
    }
    FlowInterpreter(
        lambda event, payload: events.append((event, payload))
    )._execute(flow)
    assert probe_block[0] == {"text": "原始"}  # 原参数继续执行
    warn = [p for e, p in events if e == "log" and p.get("level") == "warn"]
    assert warn
