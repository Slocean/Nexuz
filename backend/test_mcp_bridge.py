"""MCP bridge：token 鉴权、工具分发、run_block 安全闸、run_flow 路径守卫。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.core import mcp_bridge as mb
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
def fake_plugin():
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


class StubApi:
    """只提供 dispatch 所需的最小 Api 表面。"""

    def __init__(self, flows_dir: Path):
        self._flows_stub = flows_dir
        self.run_flow_calls: list[dict] = []

    def _flows_dir(self, *, create: bool = False):
        return self._flows_stub

    def _is_under_dir(self, path, folder) -> bool:
        try:
            path.resolve().relative_to(Path(folder).resolve())
            return True
        except ValueError:
            return False

    def run_flow(self, flow, **kwargs) -> dict:
        self.run_flow_calls.append(flow)
        return {"ok": True, "started": True}

    def list_flows(self) -> dict:
        return {"ok": True, "flows": [], "dir": str(self._flows_stub), "exists": True}

    def stop_flow(self) -> dict:
        return {"ok": True, "action": "stop"}

    def pause_flow(self) -> dict:
        return {"ok": True, "action": "pause"}

    def resume_flow(self) -> dict:
        return {"ok": True, "action": "resume"}


@pytest.fixture
def stub_api(tmp_path):
    api = StubApi(tmp_path / "flows")
    yield api


@pytest.fixture
def server(stub_api):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mb._make_handler("test-token", stub_api))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", "test-token", stub_api
    httpd.shutdown()
    httpd.server_close()


def rpc(base: str, token: str | None, tool: str, args: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base}/rpc",
        method="POST",
        data=json.dumps({"tool": tool, "args": args or {}}).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_health(server):
    base, _token, _api = server
    with urllib.request.urlopen(f"{base}/health", timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is True
    assert data["name"] == "nexuz-mcp"


def test_rpc_requires_token(server):
    base, token, _api = server
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        rpc(base, None, "get_status")
    assert exc_info.value.code == 401
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        rpc(base, "wrong-token", "get_status")
    assert exc_info.value.code == 401
    status, data = rpc(base, token, "get_status")
    assert status == 200 and data["ok"] is True and data["result"]["ok"] is True


def test_unknown_tool(server):
    base, token, _api = server
    _status, data = rpc(base, token, "no_such_tool")
    assert data["result"]["ok"] is False


def test_get_block_schema_unknown(server):
    base, token, _api = server
    _status, data = rpc(base, token, "get_block_schema", {"type": "no_such"})
    assert data["result"]["ok"] is False


def test_list_blocks_includes_fake(server, monkeypatch, fake_echo):
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": False, "allow_dangerous": False})
    base, token, _api = server
    _status, data = rpc(base, token, "list_blocks", {})
    types = [b["type"] for b in data["result"]["blocks"]]
    assert "fake_echo" in types


def test_run_block_gates(server, monkeypatch, fake_echo):
    from backend.core.ai import run_block as rb

    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset(rb.RUN_BLOCK_SAFE | {fake_echo}))
    base, token, _api = server

    # 未开启 allow_run_block → 拒绝
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": False, "allow_dangerous": False})
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "hi"}})
    assert data["result"]["ok"] is False and "未开启" in data["result"]["error"]

    # 开启 allow_run_block → safe 类直接执行；结果在嵌套 result 里
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": False})
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "hi"}})
    assert data["result"]["ok"] is True and data["result"]["result"]["out"] == "echo:hi"

    # 会话上下文：第二次调用可通过 {{ai_run_1.out}} 引用第一次输出
    _status, data = rpc(
        base,
        token,
        "run_block",
        {"type": fake_echo, "params": {"text": "{{ai_run_1.out}}"}},
    )
    assert data["result"]["ok"] is True and data["result"]["result"]["out"] == "echo:echo:hi"


def test_run_block_action_needs_dangerous(server, monkeypatch, fake_echo):
    from backend.core.ai import run_block as rb

    # 仅列入 ACTION（SAFE 优先级更高，同时列入会被判为 safe）
    monkeypatch.setattr(rb, "RUN_BLOCK_ACTION", frozenset(rb.RUN_BLOCK_ACTION | {fake_echo}))
    base, token, _api = server
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": False})
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "x"}})
    assert data["result"]["ok"] is False and "危险模式" in data["result"]["error"]

    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": True})
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "x"}})
    assert data["result"]["ok"] is True


def test_run_block_rejects_user_plugin(server, monkeypatch, fake_plugin):
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": True})
    base, token, _api = server
    _status, data = rpc(base, token, "run_block", {"type": fake_plugin, "params": {}})
    assert data["result"]["ok"] is False


def test_reset_session(server, monkeypatch, fake_echo):
    from backend.core.ai import run_block as rb

    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset(rb.RUN_BLOCK_SAFE | {fake_echo}))
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": False})
    base, token, _api = server
    rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "hi"}})
    assert mb._run_ctx["context"]
    _status, data = rpc(base, token, "reset_session", {})
    assert data["result"]["ok"] is True
    assert mb._run_ctx["context"] == {} and mb._run_ctx["counter"] == 0


def test_run_flow_path_guard(server):
    base, token, _api = server
    _status, data = rpc(base, token, "run_flow", {"flow_path": "C:/Windows/system32/evil.json"})
    assert data["result"]["ok"] is False and "流程库" in data["result"]["error"]
    _status, data = rpc(base, token, "run_flow", {})
    assert data["result"]["ok"] is False and "flow_path" in data["result"]["error"]


def test_run_flow_reads_library_file(server, tmp_path):
    base, token, api = server
    flow_file = tmp_path / "flows" / "demo.flow.json"
    flow_file.parent.mkdir(exist_ok=True)
    flow_file.write_text(json.dumps({"name": "demo", "nodes": {}}), encoding="utf-8")
    _status, data = rpc(base, token, "run_flow", {"flow_path": str(flow_file), "wait": False})
    assert data["result"]["run"]["started"] is True
    assert api.run_flow_calls and api.run_flow_calls[0]["name"] == "demo"


def test_flow_control(server):
    base, token, _api = server
    _status, data = rpc(base, token, "flow_control", {"action": "stop"})
    assert data["result"]["ok"] is True
    _status, data = rpc(base, token, "flow_control", {"action": "explode"})
    assert data["result"]["ok"] is False


def test_port_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "port_file_path", lambda: tmp_path / "mcp" / "port.json")
    mb._write_port_file(12345, "tok")
    raw = json.loads((tmp_path / "mcp" / "port.json").read_text(encoding="utf-8"))
    assert raw["port"] == 12345 and raw["token"] == "tok"
    mb._remove_port_file()
    assert not (tmp_path / "mcp" / "port.json").exists()


def test_get_mcp_config_defaults(monkeypatch, tmp_path):
    import backend.paths as paths

    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "config.json")
    cfg = mb.get_mcp_config()
    assert cfg["enabled"] is True and cfg["port"] == 0
