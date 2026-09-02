"""阶段6择机项：调度策略预扫描、$$ 转义、工具循环缓存、Anthropic 原生客户端。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.core.ai.providers.anthropic import AnthropicClient
from backend.core.ai.types import AiConfig, LlmError
from backend.core.registry import register_all_blocks


@pytest.fixture(autouse=True)
def _full_registry():
    register_all_blocks()


# --- 调度触发补策略预扫描 -----------------------------------------------------


class _FakeInterpreter:
    def __init__(self, running: bool = False):
        self.running = running
        self.started: list[dict] = []

    def run_flow(self, payload, step_mode=False):
        self.started.append(payload)
        self.running = True
        return {"started": True}


class _FakeRuntimeLogs:
    def start(self, payload):
        return None

    def finish(self, payload):
        return None


def test_scheduler_blocks_critical_blocks_before_start(tmp_path, monkeypatch):
    """调度触发的流程含 http_request（ELEVATED）时：safe 模式下启动前整体拒绝。"""
    from backend.core.scheduler import FlowScheduler

    failures = tmp_path / "failures.jsonl"
    monkeypatch.setattr("backend.core.scheduler._failures_file", lambda: failures)
    interp = _FakeInterpreter(running=False)
    monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
    monkeypatch.setattr("backend.core.runtime_log.get_runtime_log_manager", lambda: _FakeRuntimeLogs())

    events: list = []
    scheduler = FlowScheduler()
    scheduler._aps = None
    scheduler._jobs["job-1"] = {"trigger_type": "interval", "file_path": ""}
    scheduler.set_emit(lambda event, payload: events.append((event, payload)))

    # 未声明 execution_policy 的存量流程默认 legacy —— 不会误伤；
    # 用 safe 模式 + critical 积木验证拦截路径。
    flow = {
        "entry": "s",
        "execution_policy": {"mode": "safe"},
        "nodes": {"s": {"type": "http_request", "params": {"url": "https://example.com"}}},
    }
    scheduler._start_or_queue("job-1", flow, scheduler._jobs["job-1"])

    assert interp.started == []  # 从未启动
    status = scheduler.list_jobs()[0]
    assert status["last_failure"]["reason"] == "policy_blocked"
    assert any(e == "schedule_error" and p.get("reason") == "policy_blocked" for e, p in events)


def test_scheduler_safe_flow_still_starts(tmp_path, monkeypatch):
    from backend.core.scheduler import FlowScheduler

    failures = tmp_path / "failures.jsonl"
    monkeypatch.setattr("backend.core.scheduler._failures_file", lambda: failures)
    interp = _FakeInterpreter(running=False)
    monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
    monkeypatch.setattr("backend.core.runtime_log.get_runtime_log_manager", lambda: _FakeRuntimeLogs())

    scheduler = FlowScheduler()
    scheduler._aps = None
    scheduler._jobs["job-1"] = {"trigger_type": "interval", "file_path": ""}
    flow = {"entry": "a", "execution_policy": {"mode": "safe"}, "nodes": {"a": {"type": "delay", "params": {"ms": 10}}}}
    scheduler._start_or_queue("job-1", flow, scheduler._jobs["job-1"])
    assert len(interp.started) == 1


# --- $$ 转义 -------------------------------------------------------------------


def test_double_dollar_escape_keeps_literal():
    from backend.core.variable_resolver import resolve_value

    ctx = {"name": "张三", "cfg": {"value": 1}}
    assert resolve_value("$$name", ctx) == "$name"  # 字面量，不替换
    assert resolve_value("你好 $$name，欢迎", ctx) == "你好 $name，欢迎"
    assert resolve_value("$$cfg.value", ctx) == "$cfg.value"
    assert resolve_value("$$ 100 元", ctx) == "$$ 100 元"  # 非变量形态不视作转义
    # 普通替换不受影响
    assert resolve_value("$name", ctx) == "张三"
    assert resolve_value("你好 $name", ctx) == "你好 张三"
    assert resolve_value("{{name}}", ctx) == "张三"
    # 转义与替换可混用
    assert resolve_value("$name 和 $$name", ctx) == "张三 和 $name"


# --- 工具循环缓存 ---------------------------------------------------------------


def test_action_loop_cache_hit_on_same_messages(tmp_path, monkeypatch):
    from backend.core.ai import llm_cache
    from backend.core.ai.graphs import flow_graph as fg

    cache_root = tmp_path / "ai"

    def _ai_dir(*, create: bool = False):
        if create:
            cache_root.mkdir(parents=True, exist_ok=True)
        return cache_root

    monkeypatch.setattr("backend.paths.ai_dir", _ai_dir)
    monkeypatch.setattr("backend.paths.config_path", lambda: tmp_path / "config.json")
    llm_cache.close_cache()
    try:
        calls = {"n": 0}

        def fake_invoke(llm, schema, messages, compact_messages=None):
            calls["n"] += 1
            return schema(actions=[])

        monkeypatch.setattr(fg, "invoke_structured", fake_invoke)
        cfg = AiConfig(model="m1", base_url="https://x/v1", llm_cache_enabled=True)
        msgs = [{"role": "user", "content": "task"}]

        r1 = fg._invoke_action_loop_cached(None, fg.ToolActionBatch, msgs, [], cfg)
        r2 = fg._invoke_action_loop_cached(None, fg.ToolActionBatch, msgs, [], cfg)
        assert calls["n"] == 1  # 第二次命中缓存
        assert r1 == r2

        # 消息变化 → miss
        fg._invoke_action_loop_cached(None, fg.ToolActionBatch, [{"role": "user", "content": "task2"}], [], cfg)
        assert calls["n"] == 2
    finally:
        llm_cache.close_cache()


# --- Anthropic 原生客户端 --------------------------------------------------------


class _Capture:
    """httpx.MockTransport handler 工厂：记录请求并返回固定响应。"""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body or {}
        self.captured: dict = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.captured.update(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": json.loads(request.content.decode("utf-8")) if request.content else {},
            }
        )
        return httpx.Response(self.status, json=self.body)


def test_anthropic_url_building():
    from backend.core.ai.providers.anthropic import _messages_url

    assert _messages_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    assert _messages_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
    assert (
        _messages_url("https://gw.example.com/anthropic/v1/")
        == "https://gw.example.com/anthropic/v1/messages"
    )


def test_anthropic_chat_maps_messages_and_tools():
    cap = _Capture(
        body={
            "content": [
                {"type": "text", "text": "好的"},
                {"type": "tool_use", "id": "tu_1", "name": "run_block", "input": {"type": "delay"}},
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
    )
    captured = cap.captured

    client = AnthropicClient(
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-5",
        http_client=httpx.Client(transport=httpx.MockTransport(cap)),
    )
    turn = client.chat(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tu_0", "type": "function", "function": {"name": "capture", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "tu_0", "content": "截图完成"},
        ],
        tools=[{"type": "function", "function": {"name": "run_block", "description": "跑积木", "parameters": {"type": "object", "properties": {}}}}],
    )

    # 请求形态
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["json"]
    assert body["system"] == "你是助手"
    assert body["max_tokens"] == 4096
    assert body["tools"][0]["name"] == "run_block"
    assert body["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    # assistant tool_calls → assistant content 内 tool_use；tool → 下一条 user 内 tool_result
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert body["messages"][1]["content"][0]["type"] == "tool_use"
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["messages"][2]["content"][0]["tool_use_id"] == "tu_0"

    # 响应映射：OpenAI 风格 tool_calls + usage 透传
    assert turn.content == "好的"
    assert turn.tool_calls[0]["function"]["name"] == "run_block"
    assert json.loads(turn.tool_calls[0]["function"]["arguments"]) == {"type": "delay"}
    assert turn.usage == {"input_tokens": 11, "output_tokens": 7}


def test_anthropic_fixed_temperature_applied():
    cap = _Capture(body={"content": [{"type": "text", "text": "ok"}]})
    captured = cap.captured

    client = AnthropicClient(
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="kimi-claude",  # 命中 kimi 固定温度 0.6
        temperature=0.7,
        http_client=httpx.Client(transport=httpx.MockTransport(cap)),
    )
    client.chat([{"role": "user", "content": "hi"}])
    assert captured["json"]["temperature"] == 0.6


def test_anthropic_http_error_raises_llm_error():
    cap = _Capture(status=401, body={"error": {"message": "invalid x-api-key"}})
    client = AnthropicClient(
        base_url="https://api.anthropic.com",
        api_key="bad",
        model="claude-sonnet-4-5",
        http_client=httpx.Client(transport=httpx.MockTransport(cap)),
    )
    with pytest.raises(LlmError, match="401"):
        client.chat([{"role": "user", "content": "hi"}])


def test_anthropic_requires_api_key():
    client = AnthropicClient(base_url="https://api.anthropic.com", api_key="", model="claude-sonnet-4-5")
    with pytest.raises(LlmError, match="API Key"):
        client.chat([{"role": "user", "content": "hi"}])


def test_llm_client_factory_returns_anthropic():
    from backend.core.ai.llm_client import create_llm_client
    from backend.core.ai.providers.anthropic import AnthropicClient as _C

    client = create_llm_client(AiConfig(provider="anthropic", api_key="sk-ant-x", model="claude-sonnet-4-5"))
    assert isinstance(client, _C)
