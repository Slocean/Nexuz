"""LLM 桥接积木测试：格式互转内核 + llm_convert / llm_forward 行为与接线分级。

侧重点：chat/completions ↔ responses 双向请求/响应映射的语义保真（工具调用
往返、usage 换名、错误体透传）、转换不改输入、转发积木经本地 HTTP 服务的
端到端链路（请求体直转不包装 / 端点路由 / 设置回退 / 转换往返 / HTTP 错误
与非 JSON 响应），以及新积木在执行策略与 AI run_block 里的分级。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from backend.blocks import _llm_formats as core
from backend.blocks import llm_convert, llm_forward

# --- 测试样例 ---------------------------------------------------------------

CHAT_REQUEST = {
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "晴天 25 度"},
    ],
    "temperature": 0.5,
    "max_tokens": 1024,
    "tools": [
        {
            "type": "function",
            "function": {"name": "get_weather", "description": "查天气", "parameters": {"type": "object", "properties": {}}},
        }
    ],
    "tool_choice": "auto",
}

RESPONSES_REQUEST = {
    "model": "gpt-4o",
    "instructions": "你是一个助手",
    "input": [
        {"role": "user", "content": "你好"},
        {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": '{"city": "北京"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "晴天 25 度"},
    ],
    "temperature": 0.5,
    "max_output_tokens": 1024,
    "tools": [
        {"type": "function", "name": "get_weather", "description": "查天气", "parameters": {"type": "object", "properties": {}}}
    ],
    "tool_choice": "auto",
}

CHAT_RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "你好！有什么可以帮你？"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
}

RESPONSES_RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1700000000,
    "model": "gpt-4o",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "你好！有什么可以帮你？", "annotations": []}],
        }
    ],
    "status": "completed",
    "usage": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
}


# --- 格式探测 ---------------------------------------------------------------


class TestDetect:
    def test_request_formats(self):
        assert core.detect_request_format(CHAT_REQUEST) == core.CHAT
        assert core.detect_request_format(RESPONSES_REQUEST) == core.RESPONSES
        assert core.detect_request_format({"foo": 1}) == core.UNKNOWN

    def test_response_formats(self):
        assert core.detect_response_format(CHAT_RESPONSE) == core.CHAT
        assert core.detect_response_format(RESPONSES_RESPONSE) == core.RESPONSES
        assert core.detect_response_format({"foo": 1}) == core.UNKNOWN

    def test_detect_kind(self):
        assert core.detect_kind(CHAT_REQUEST) == "request"
        assert core.detect_kind(RESPONSES_RESPONSE) == "response"
        with pytest.raises(ValueError):
            core.detect_kind({"foo": 1})


# --- 请求转换 ---------------------------------------------------------------


class TestRequestConversion:
    def test_chat_to_responses(self):
        out = core.chat_to_responses_request(CHAT_REQUEST)
        assert out["model"] == "gpt-4o"
        assert out["temperature"] == 0.5
        assert out["max_output_tokens"] == 1024
        assert out["input"][0] == {"role": "system", "content": "你是一个助手"}
        assert out["input"][1] == {"role": "user", "content": "你好"}
        assert out["input"][2] == {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": '{"city": "北京"}'}
        assert out["input"][3] == {"type": "function_call_output", "call_id": "call_1", "output": "晴天 25 度"}
        assert out["tools"] == [
            {"type": "function", "name": "get_weather", "description": "查天气", "parameters": {"type": "object", "properties": {}}}
        ]
        assert out["tool_choice"] == "auto"

    def test_responses_to_chat(self):
        out = core.responses_to_chat_request(RESPONSES_REQUEST)
        assert out["model"] == "gpt-4o"
        assert out["temperature"] == 0.5
        assert out["max_tokens"] == 1024
        # instructions → 系统消息排在最前
        assert out["messages"][0] == {"role": "system", "content": "你是一个助手"}
        assert out["messages"][1] == {"role": "user", "content": "你好"}
        assert out["messages"][2]["role"] == "assistant"
        assert out["messages"][2]["tool_calls"] == [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}}
        ]
        assert out["messages"][2]["content"] is None
        assert out["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "晴天 25 度"}
        assert out["tools"][0]["type"] == "function"
        assert out["tools"][0]["function"]["name"] == "get_weather"

    def test_responses_input_string(self):
        out = core.responses_to_chat_request({"model": "m", "input": "直接一句话"})
        assert out["messages"] == [{"role": "user", "content": "直接一句话"}]

    def test_chat_to_responses_roundtrip_semantics(self):
        chat = json.loads(json.dumps(CHAT_REQUEST))  # 深拷贝
        to_responses = core.chat_to_responses_request(chat)
        back = core.responses_to_chat_request(to_responses)
        assert back["model"] == chat["model"]
        assert back["temperature"] == chat["temperature"]
        assert back["max_tokens"] == chat["max_tokens"]
        assert back["messages"][0] == {"role": "system", "content": "你是一个助手"}
        assert back["messages"][1] == {"role": "user", "content": "你好"}
        assert back["messages"][2]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert back["messages"][3]["tool_call_id"] == "call_1"
        assert back["tools"][0]["function"]["name"] == "get_weather"

    def test_convert_does_not_mutate_input(self):
        original = json.loads(json.dumps(CHAT_REQUEST))
        core.chat_to_responses_request(CHAT_REQUEST)
        assert CHAT_REQUEST == original

    def test_response_format_mapping(self):
        chat = {"model": "m", "messages": [], "response_format": {"type": "json_object"}}
        out = core.chat_to_responses_request(chat)
        assert out["text"] == {"format": {"type": "json_object"}}
        chat_schema = {
            "model": "m",
            "messages": [],
            "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": {"type": "object"}, "strict": True}},
        }
        out = core.chat_to_responses_request(chat_schema)
        assert out["text"]["format"]["name"] == "out"
        assert out["text"]["format"]["strict"] is True
        back = core.responses_to_chat_request({"input": [], "text": {"format": {"type": "json_object"}}})
        assert back["response_format"] == {"type": "json_object"}

    def test_bad_payloads(self):
        with pytest.raises(ValueError):
            core.chat_to_responses_request({"model": "m"})
        with pytest.raises(ValueError):
            core.responses_to_chat_request({"model": "m"})
        with pytest.raises(ValueError):
            core.convert([], source=core.CHAT, target=core.RESPONSES, kind="request")


# --- 响应转换 ---------------------------------------------------------------


class TestResponseConversion:
    def test_chat_to_responses(self):
        out = core.chat_to_responses_response(CHAT_RESPONSE)
        assert out["object"] == "response"
        assert out["status"] == "completed"
        assert out["output_text"] == "你好！有什么可以帮你？"
        assert out["output"][0]["content"][0]["text"] == "你好！有什么可以帮你？"
        assert out["usage"]["input_tokens"] == 10
        assert out["usage"]["output_tokens"] == 8
        assert out["created_at"] == 1700000000

    def test_responses_to_chat(self):
        out = core.responses_to_chat_response(RESPONSES_RESPONSE)
        assert out["object"] == "chat.completion"
        choice = out["choices"][0]
        assert choice["message"]["content"] == "你好！有什么可以帮你？"
        assert choice["finish_reason"] == "stop"
        assert out["usage"]["prompt_tokens"] == 10
        assert out["usage"]["completion_tokens"] == 8

    def test_tool_calls_finish_reason(self):
        resp = {
            "object": "response",
            "output": [
                {"type": "message", "role": "assistant", "content": []},
                {"type": "function_call", "call_id": "call_9", "name": "f", "arguments": "{}"},
            ],
            "status": "completed",
        }
        out = core.responses_to_chat_response(resp)
        msg = out["choices"][0]["message"]
        assert out["choices"][0]["finish_reason"] == "tool_calls"
        assert msg["tool_calls"][0]["id"] == "call_9"
        assert msg["content"] is None

    def test_length_finish_maps_to_incomplete(self):
        chat = dict(CHAT_RESPONSE, choices=[dict(CHAT_RESPONSE["choices"][0], finish_reason="length")])
        out = core.chat_to_responses_response(chat)
        assert out["status"] == "incomplete"
        assert out["incomplete_details"] == {"reason": "max_output_tokens"}
        back = core.responses_to_chat_response(out)
        assert back["choices"][0]["finish_reason"] == "length"

    def test_error_payload_passthrough(self):
        chat_err = {"error": {"message": "配额不足", "type": "insufficient_quota"}}
        out = core.chat_to_responses_response(chat_err)
        assert out["status"] == "failed"
        assert out["error"]["message"] == "配额不足"
        back = core.responses_to_chat_response(out)
        assert back["error"]["type"] == "insufficient_quota"

    def test_response_roundtrip_text(self):
        to_responses = core.chat_to_responses_response(CHAT_RESPONSE)
        back = core.responses_to_chat_response(to_responses)
        assert back["choices"][0]["message"]["content"] == CHAT_RESPONSE["choices"][0]["message"]["content"]
        assert back["usage"]["total_tokens"] == 18

    def test_extract_response_text_both_formats(self):
        assert core.extract_response_text(CHAT_RESPONSE) == "你好！有什么可以帮你？"
        assert core.extract_response_text(RESPONSES_RESPONSE) == "你好！有什么可以帮你？"
        assert core.extract_response_text({"foo": 1}) == ""
        assert core.extract_response_text("not a dict") == ""


# --- llm_convert 积木 --------------------------------------------------------


class TestLlmConvertBlock:
    def test_convert_request_from_string(self):
        out = llm_convert.handler({"payload": json.dumps(CHAT_REQUEST, ensure_ascii=False), "source": "auto", "target": "responses"}, None)
        assert out["ok"] is True
        assert out["source"] == "chat" and out["target"] == "responses" and out["kind"] == "request"
        assert out["converted"]["max_output_tokens"] == 1024

    def test_convert_response_from_dict(self):
        out = llm_convert.handler({"payload": RESPONSES_RESPONSE, "target": "chat"}, None)
        assert out["ok"] is True
        assert out["kind"] == "response"
        assert out["converted"]["choices"][0]["message"]["content"] == "你好！有什么可以帮你？"

    def test_same_format_passthrough(self):
        out = llm_convert.handler({"payload": CHAT_REQUEST, "source": "chat", "target": "chat"}, None)
        assert out["ok"] is True
        assert out["converted"] == CHAT_REQUEST

    def test_json_string_output(self):
        out = llm_convert.handler({"payload": CHAT_REQUEST, "target": "responses"}, None)
        assert json.loads(out["json"]) == out["converted"]

    def test_errors(self):
        assert llm_convert.handler({"payload": ""}, None)["ok"] is False
        assert "JSON" in llm_convert.handler({"payload": "{bad"}, None)["error"]
        assert llm_convert.handler({"payload": "[1,2]"}, None)["ok"] is False
        assert "无法识别" in llm_convert.handler({"payload": {"foo": 1}, "target": "chat"}, None)["error"]


# --- llm_forward 积木（本地 HTTP 服务） --------------------------------------


_REQUEST_LOG = {"path": "", "auth": "", "x_custom": "", "body": {}}


class _EchoLLMHandler(BaseHTTPRequestHandler):
    """回显式假端点：按请求体格式应答（messages→chat / input→responses），记录请求供断言。"""

    def do_POST(self):  # noqa: N802 - http.server 命名约定
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            req = {}
        _REQUEST_LOG.update(
            {"path": self.path, "auth": self.headers.get("Authorization"), "x_custom": self.headers.get("X-Custom"), "body": req}
        )
        if "messages" in req:
            resp = {
                "id": "chatcmpl-x",
                "object": "chat.completion",
                "created": 1700000000,
                "model": req.get("model") or "m",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "echo"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            }
        elif "input" in req:
            resp = {
                "id": "resp-x",
                "object": "response",
                "model": req.get("model") or "m",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "echo", "annotations": []}],
                    }
                ],
                "status": "completed",
                "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
            }
        else:
            resp = {"error": {"message": "无法识别格式"}}
        data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默测试输出
        pass


@pytest.fixture(scope="module")
def echo_server():
    server = HTTPServer(("127.0.0.1", 0), _EchoLLMHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"  # base_url，路径由积木自动拼
    server.shutdown()


@pytest.fixture()
def ai_cfg(monkeypatch):
    """模拟「设置 → Nexuz AI」的服务商配置，避免读到真实配置文件。"""
    cfg = SimpleNamespace(base_url="", api_key="", model="test-model")
    monkeypatch.setattr(llm_forward, "get_ai_config", lambda: cfg)
    return cfg


class TestLlmForwardBlock:
    def test_simple_mode_forwards_body_as_is(self, echo_server, ai_cfg):
        out = llm_forward.handler({"payload": CHAT_REQUEST, "base_url": echo_server, "api_key": "sk-x"}, None)
        assert out["ok"] is True and out["status"] == 200
        assert out["text"] == "echo"
        assert _REQUEST_LOG["path"] == "/chat/completions"
        assert _REQUEST_LOG["auth"] == "Bearer sk-x"
        # 请求体原样转发：字段不增不减不包装
        assert _REQUEST_LOG["body"] == CHAT_REQUEST

    def test_model_autofill_when_body_lacks_model(self, echo_server, ai_cfg):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        out = llm_forward.handler({"payload": body, "base_url": echo_server, "api_key": "sk-x"}, None)
        assert out["ok"] is True
        assert _REQUEST_LOG["body"]["model"] == "test-model"  # 设置里的模型自动补齐

    def test_model_param_overrides(self, echo_server, ai_cfg):
        out = llm_forward.handler(
            {"payload": CHAT_REQUEST, "base_url": echo_server, "api_key": "sk-x", "model": "my-model"},
            None,
        )
        assert out["ok"] is True
        assert _REQUEST_LOG["body"]["model"] == "my-model"

    def test_responses_body_routes_to_responses_endpoint(self, echo_server, ai_cfg):
        out = llm_forward.handler({"payload": RESPONSES_REQUEST, "base_url": echo_server, "api_key": "sk-x"}, None)
        assert out["ok"] is True
        assert out["response"]["object"] == "response"
        assert _REQUEST_LOG["path"] == "/responses"

    def test_full_endpoint_url_passthrough(self, echo_server, ai_cfg):
        out = llm_forward.handler({"payload": CHAT_REQUEST, "base_url": echo_server + "/chat/completions", "api_key": "sk-x"}, None)
        assert out["ok"] is True
        assert _REQUEST_LOG["path"] == "/chat/completions"

    def test_settings_fallback_for_base_url_and_key(self, echo_server, ai_cfg):
        ai_cfg.base_url = echo_server
        ai_cfg.api_key = "sk-from-settings"
        out = llm_forward.handler({"payload": CHAT_REQUEST}, None)
        assert out["ok"] is True
        assert _REQUEST_LOG["auth"] == "Bearer sk-from-settings"

    def test_extra_headers_reach_endpoint(self, echo_server, ai_cfg):
        out = llm_forward.handler(
            {"payload": CHAT_REQUEST, "base_url": echo_server, "api_key": "sk-x", "headers": {"X-Custom": "yes"}},
            None,
        )
        assert out["ok"] is True
        assert _REQUEST_LOG["x_custom"] == "yes"

    def test_conversion_roundtrip(self, echo_server, ai_cfg):
        # 入口 chat → 出口 responses → 路由到 /responses → 响应转回 chat
        out = llm_forward.handler(
            {"payload": CHAT_REQUEST, "base_url": echo_server, "api_key": "sk-x", "convert": "chat_to_responses"},
            None,
        )
        assert out["ok"] is True
        assert _REQUEST_LOG["path"] == "/responses"
        assert out["response"]["object"] == "chat.completion"
        assert out["text"] == "echo"

    def test_error_cases(self, echo_server, ai_cfg):
        out = llm_forward.handler({"payload": ""}, None)
        assert out["ok"] is False and "为空" in out["error"]
        # 不是对话积木：普通文本不是合法请求体
        out = llm_forward.handler({"payload": "你好", "base_url": echo_server}, None)
        assert out["ok"] is False and "JSON" in out["error"]
        out = llm_forward.handler({"payload": ["不", "是", "对象"], "base_url": echo_server}, None)
        assert out["ok"] is False and "JSON 对象" in out["error"]
        out = llm_forward.handler({"payload": "{}", "base_url": echo_server}, None)
        assert out["ok"] is False and "无法识别" in out["error"]
        out = llm_forward.handler({"payload": CHAT_REQUEST, "base_url": echo_server, "convert": "bogus"}, None)
        assert out["ok"] is False and "未知转换方向" in out["error"]
        # 无 base_url 且设置为空
        out = llm_forward.handler({"payload": CHAT_REQUEST}, None)
        assert out["ok"] is False and "Base URL 为空" in out["error"]

    def test_http_error_carries_body(self, ai_cfg):
        class _ErrHandler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                data = '{"error": {"message": "配额不足"}}'.encode("utf-8")
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _ErrHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            out = llm_forward.handler({"payload": CHAT_REQUEST, "base_url": url}, None)
        finally:
            server.shutdown()
        assert out["ok"] is False and out["status"] == 429
        assert out["response"]["error"]["message"] == "配额不足"

    def test_non_json_response(self, ai_cfg):
        class _TextHandler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                data = b"hello world"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _TextHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            out = llm_forward.handler({"payload": CHAT_REQUEST, "base_url": url}, None)
        finally:
            server.shutdown()
        assert out["ok"] is False
        assert "响应不是 JSON" in out["error"]
        assert out["response_json"] == "hello world"


# --- 接线分级 ---------------------------------------------------------------


class TestWiring:
    def test_registry_contains_blocks(self):
        from backend.core.registry import register_all_blocks

        schemas = register_all_blocks()
        for block_type in ("llm_convert", "llm_forward"):
            assert block_type in schemas, block_type
            assert schemas[block_type]["handler"] is not None

    def test_run_block_tiers(self):
        from backend.core.ai.run_block import RUN_BLOCK_ACTION, RUN_BLOCK_SAFE

        assert "llm_convert" in RUN_BLOCK_SAFE
        assert "llm_forward" in RUN_BLOCK_ACTION

    def test_execution_policy_elevated(self):
        from backend.core.execution_policy import CAPABILITY_LABELS, ELEVATED_TYPES

        assert "llm_forward" in ELEVATED_TYPES
        assert "llm_forward" in CAPABILITY_LABELS

    def test_forward_schema_has_mode_switch(self):
        from backend.core.registry import register_all_blocks

        schemas = register_all_blocks()
        inputs = {i["name"]: i for i in schemas["llm_forward"]["schema"]["inputs"]}
        assert inputs["mode"]["default"] == "simple"
        for name in ("model", "convert", "headers", "timeout_sec"):
            assert inputs[name].get("show_when") == {"mode": "custom"}, name
        for name in ("payload", "base_url", "api_key"):
            assert "show_when" not in inputs[name], name
        assert "system" not in inputs  # 转发器不是对话节点，不做对话包装
