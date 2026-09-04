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


@pytest.fixture
def fake_critical():
    """危险命令类积木（CRITICAL_TYPES）；若真实块已注册则原样保留。"""
    previous = BLOCK_REGISTRY.get("run_command")
    schema = {
        "type": "run_command",
        "label": "执行系统命令",
        "category": "系统类",
        "inputs": [],
        "outputs": [],
    }
    register_block(schema, lambda params, context, **kwargs: {})
    yield "run_command"
    if previous is None:
        BLOCK_REGISTRY.pop("run_command", None)
    else:
        BLOCK_REGISTRY["run_command"] = previous


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


def test_list_blocks_includes_fake(server, fake_echo, fake_critical):
    base, token, _api = server
    _status, data = rpc(base, token, "list_blocks", {})
    types = [b["type"] for b in data["result"]["blocks"]]
    assert "fake_echo" in types
    # 危险命令类不进入外部 AI 目录
    assert "run_command" not in types


def test_get_block_schema_critical_denied(server, fake_critical):
    base, token, _api = server
    _status, data = rpc(base, token, "get_block_schema", {"type": fake_critical})
    assert data["result"]["ok"] is False and "不可由外部 AI 执行" in data["result"]["error"]


def test_run_block_open_without_switches(server, monkeypatch, fake_echo):
    """MCP run_block 不再要求应用内开关（授权由接入的 AI 客户端负责）。"""
    from backend.core.ai import run_block as rb

    monkeypatch.setattr(rb, "RUN_BLOCK_SAFE", frozenset(rb.RUN_BLOCK_SAFE | {fake_echo}))
    base, token, _api = server

    # 双开关全关 → safe 类仍直接执行；结果在嵌套 result 里
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": False, "allow_dangerous": False})
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "hi"}})
    assert data["result"]["ok"] is True and data["result"]["result"]["out"] == "echo:hi"

    # ACTION 档（真实副作用类）同样无需危险模式开关
    monkeypatch.setattr(rb, "RUN_BLOCK_ACTION", frozenset(rb.RUN_BLOCK_ACTION | {fake_echo}))
    _status, data = rpc(base, token, "run_block", {"type": fake_echo, "params": {"text": "x"}})
    assert data["result"]["ok"] is True

    # 会话上下文：第二次调用可通过 {{ai_run_1.out}} 引用第一次输出
    _status, data = rpc(
        base,
        token,
        "run_block",
        {"type": fake_echo, "params": {"text": "{{ai_run_1.out}}"}},
    )
    assert data["result"]["ok"] is True and data["result"]["result"]["out"] == "echo:echo:hi"


def test_run_block_denies_critical(server, monkeypatch, fake_critical):
    monkeypatch.setattr(mb, "_ai_cfg", lambda: {"allow_run_block": True, "allow_dangerous": True})
    base, token, _api = server
    _status, data = rpc(base, token, "run_block", {"type": fake_critical, "params": {}})
    assert data["result"]["ok"] is False and "不支持 AI 实时执行" in data["result"]["error"]


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


def test_run_flow_rejects_critical_inline(server):
    """内联流程携带 python_script → 无论开关状态一律拒绝。"""
    base, token, api = server
    flow = {"name": "evil", "entry": "n1", "nodes": {"n1": {"type": "python_script", "params": {}}}}
    _status, data = rpc(base, token, "run_flow", {"flow": flow, "wait": False})
    assert data["result"]["ok"] is False and "不可执行" in data["result"]["error"]
    assert api.run_flow_calls == []


def test_run_flow_rejects_power_action_inline(server):
    base, token, api = server
    flow = {"name": "evil", "entry": "n1", "nodes": {"n1": {"type": "power_action", "params": {}}}}
    _status, data = rpc(base, token, "run_flow", {"flow": flow, "wait": False})
    assert data["result"]["ok"] is False and api.run_flow_calls == []


def test_run_flow_rejects_user_plugin_inline(server, fake_plugin):
    base, token, api = server
    flow = {"name": "evil", "entry": "n1", "nodes": {"n1": {"type": fake_plugin, "params": {}}}}
    _status, data = rpc(base, token, "run_flow", {"flow": flow, "wait": False})
    assert data["result"]["ok"] is False and api.run_flow_calls == []


def test_run_flow_rejects_critical_library_file(server, tmp_path):
    """流程库文件内的 run_command（legacy 无策略字段）→ 拒绝。"""
    base, token, api = server
    flow_file = tmp_path / "flows" / "evil.flow.json"
    flow_file.parent.mkdir(exist_ok=True)
    flow_file.write_text(
        json.dumps(
            {
                "name": "evil",
                "entry": "n1",
                "nodes": {"n1": {"type": "run_command", "params": {}}},
            }
        ),
        encoding="utf-8",
    )
    _status, data = rpc(base, token, "run_flow", {"flow_path": str(flow_file), "wait": False})
    assert data["result"]["ok"] is False and api.run_flow_calls == []


def test_run_flow_inline_normal_gets_floor_markers(server, fake_echo):
    """正常流程放行且注入来源/下限标记（运行期逐节点强制 + 定时再触发用）。"""
    base, token, api = server
    flow = {
        "name": "demo",
        "entry": "n1",
        "nodes": {"n1": {"type": fake_echo, "params": {"text": "hi"}}},
    }
    _status, data = rpc(base, token, "run_flow", {"flow": flow, "wait": False})
    assert data["result"]["ok"] is True
    sent = api.run_flow_calls[0]
    assert sent["__run_origin__"] == "mcp"
    assert "python_script" in sent["__policy_floor__"]["deny"]
    assert "power_action" in sent["__policy_floor__"]["deny"]


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


def test_flow_control_not_blocked_by_run_lock(server):
    """run_flow(wait=True) 持有 _run_lock 时，stop 仍必须可达（止损通道）。"""
    base, token, _api = server
    with mb._run_lock:
        status, data = rpc(base, token, "flow_control", {"action": "stop"})
    assert status == 200 and data["result"]["ok"] is True


def test_run_flow_wait_timeout_reports_timed_out(server, monkeypatch):
    """wait=True 超时后流程仍在运行 → timed_out:true（而非静默 finished:null）。"""
    base, token, _api = server

    class _StubInterp:
        running = True  # wait 超时后仍在执行

        def wait_until_idle(self, timeout=None):
            self.waited = timeout
            return None

    stub = _StubInterp()
    monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: stub)
    flow_file = _api._flows_dir() / "demo.flow.json"
    flow_file.parent.mkdir(exist_ok=True)
    flow_file.write_text(json.dumps({"name": "demo", "nodes": {}}), encoding="utf-8")
    _status, data = rpc(base, token, "run_flow", {"flow_path": "demo.flow.json", "wait": True, "timeout_s": 1})
    result = data["result"]
    assert result["ok"] is True
    assert result["timed_out"] is True
    assert stub.waited == 1
    assert result["finished"] is None


def test_rpc_concurrency_limit(server, monkeypatch):
    """在途 RPC 达到上限 → 503 busy（而不是无限堆线程）。"""
    import urllib.error

    base, token, _api = server
    acquired = []
    while mb._rpc_slots.acquire(blocking=False):
        acquired.append(True)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            rpc(base, token, "get_status")
        assert exc_info.value.code == 503
    finally:
        for _ in acquired:
            mb._rpc_slots.release()
