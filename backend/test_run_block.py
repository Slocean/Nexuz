"""run_block：分类闸、参数校验、会话上下文与 ToolRuntime 分发。"""

from __future__ import annotations

import pytest

from backend.core.ai import run_block as rb
from backend.core.registry import BLOCK_REGISTRY, register_block


@pytest.fixture
def fake_echo():
    schema = {
        "type": "fake_echo",
        "label": "回显",
        "category": "识别类",
        "inputs": [
            {"name": "text", "type": "string", "label": "文本", "required": True},
        ],
        "outputs": [{"name": "out", "type": "string"}],
    }

    def handler(params, context, **kwargs):
        return {"out": f"echo:{params.get('text')}"}

    register_block(schema, handler)
    yield "fake_echo"
    BLOCK_REGISTRY.pop("fake_echo", None)


@pytest.fixture
def fake_user_plugin():
    schema = {
        "type": "fake_plugin",
        "label": "插件",
        "category": "系统类",
        "trust_tier": "user_plugin",
        "inputs": [],
        "outputs": [],
    }
    register_block(schema, lambda params, context, **kwargs: {})
    yield "fake_plugin"
    BLOCK_REGISTRY.pop("fake_plugin", None)


def test_classify_tiers(fake_echo, fake_user_plugin):
    assert rb.classify_run_block("screenshot") == "safe"
    assert rb.classify_run_block("delay") == "safe"
    assert rb.classify_run_block("click") == "action"
    assert rb.classify_run_block("file_io") == "action"
    # 拒绝默认：critical / 控制流 / 用户插件 / 未知
    assert rb.classify_run_block("python_script") is None
    assert rb.classify_run_block("run_command") is None
    assert rb.classify_run_block("if_condition") is None
    assert rb.classify_run_block("loop_n") is None
    assert rb.classify_run_block("try_catch") is None
    assert rb.classify_run_block("switch") is None
    assert rb.classify_run_block("no_such_block") is None


def test_requires_master_switch(fake_echo, monkeypatch):
    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset({*rb.RUN_BLOCK_SAFE, "fake_echo"}))
    out = rb.run_block_once({"type": "fake_echo", "params": {"text": "hi"}}, run_ctx={})
    assert out["ok"] is False
    assert "未开启" in out["error"]


def test_action_requires_dangerous(fake_echo, monkeypatch):
    monkeypatch.setattr(
        rb, "RUN_BLOCK_ACTION", frozenset({*rb.RUN_BLOCK_ACTION, "fake_echo"})
    )
    out = rb.run_block_once(
        {"type": "fake_echo", "params": {"text": "hi"}},
        run_ctx={},
        allow_run_block=True,
    )
    assert out["ok"] is False
    assert "危险模式" in out["error"]

    ok = rb.run_block_once(
        {"type": "fake_echo", "params": {"text": "hi"}},
        run_ctx={},
        allow_run_block=True,
        allow_dangerous=True,
    )
    assert ok["ok"] is True


def test_user_plugin_always_denied(fake_user_plugin):
    out = rb.run_block_once(
        {"type": "fake_plugin", "params": {}},
        run_ctx={},
        allow_run_block=True,
        allow_dangerous=True,
    )
    assert out["ok"] is False
    assert "自定义积木" in out["error"]


def test_param_validation(fake_echo, monkeypatch):
    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset({*rb.RUN_BLOCK_SAFE, "fake_echo"}))
    out = rb.run_block_once(
        {"type": "fake_echo", "params": {}},  # 缺必填 text
        run_ctx={},
        allow_run_block=True,
    )
    assert out["ok"] is False
    assert "参数校验失败" in out["error"]


def test_session_context_and_bindings(fake_echo, monkeypatch):
    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset({*rb.RUN_BLOCK_SAFE, "fake_echo"}))
    run_ctx: dict = {}
    r1 = rb.run_block_once(
        {"type": "fake_echo", "params": {"text": "第一步"}},
        run_ctx=run_ctx,
        allow_run_block=True,
    )
    assert r1["ok"] is True and r1["node_id"] == "ai_run_1"
    assert run_ctx["context"]["ai_run_1.out"] == "echo:第一步"

    # 第二次调用可通过 {{...}} 绑定引用上一步输出
    r2 = rb.run_block_once(
        {"type": "fake_echo", "params": {"text": "{{ai_run_1.out}}"}},
        run_ctx=run_ctx,
        allow_run_block=True,
    )
    assert r2["ok"] is True and r2["node_id"] == "ai_run_2"
    assert run_ctx["context"]["ai_run_2.out"] == "echo:echo:第一步"


def test_unknown_block_denied():
    out = rb.run_block_once(
        {"type": "no_such", "params": {}}, run_ctx={}, allow_run_block=True
    )
    assert out["ok"] is False
    assert "未知积木" in out["error"]


def test_tool_runtime_dispatch(fake_echo, monkeypatch):
    from backend.core.ai.lc.tools import ToolSession

    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset({*rb.RUN_BLOCK_SAFE, "fake_echo"}))
    session = ToolSession(draft={"nodes": {}}, allow_run_block=True)
    # 开启时工具表含 run_block
    tools = __import__(
        "backend.core.ai.lc.tools", fromlist=["build_orchestration_tools"]
    ).build_orchestration_tools(session)
    assert any(t.name == "run_block" for t in tools)

    out = session.run("run_block", {"type": "fake_echo", "params": {"text": "rt"}})
    assert out["ok"] is True
    assert out["result"]["out"] == "echo:rt"
    assert session.run_ctx["context"]["ai_run_1.out"] == "echo:rt"


def test_tool_runtime_hidden_when_disabled(fake_echo):
    from backend.core.ai.lc.tools import ToolSession, build_orchestration_tools

    session = ToolSession(draft={"nodes": {}}, allow_run_block=False)
    tools = build_orchestration_tools(session)
    assert not any(t.name == "run_block" for t in tools)
    out = session.run("run_block", {"type": "fake_echo", "params": {"text": "x"}})
    assert out["ok"] is False


def test_delay_clamped():
    params = {"ms": 999_999}
    rb._clamp_wait("delay", params)
    assert params["ms"] == rb._MAX_DELAY_MS

    params2 = {"ms": 500}
    rb._clamp_wait("delay", params2)
    assert params2["ms"] == 500

    # 非 delay 积木不受影响
    params3 = {"ms": 999_999}
    rb._clamp_wait("ocr_recognize", params3)
    assert params3["ms"] == 999_999
