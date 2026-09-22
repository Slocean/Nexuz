"""无头服务器入口：ServerApi 门面、token 持久化、真实 bridge HTTP 闭环。"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

from backend.core import host_mode
from backend.core import mcp_bridge as mb
from backend.core.host_mode import set_headless
from backend.core.registry import BLOCK_REGISTRY


@pytest.fixture(autouse=True)
def _blocks_registered():
    """确保真实积木注册表就绪（同 test_requires_gate：只补缺）。"""
    import importlib

    from backend.core.registry import register_block

    for name in (
        "click", "drag", "key_press", "mouse_hover", "mouse_scroll", "type_text",
        "screenshot", "color_detect", "find_image", "locate_text", "if_color_match",
        "window_activate", "window_close", "window_wait", "notify", "volume_action",
        "power_action", "clipboard", "delay", "monitor_start", "monitor_check",
        "monitor_wait", "monitor_list", "monitor_stop", "open_path", "system_info",
        "wait_until", "timestamp", "http_request",
    ):
        if name in BLOCK_REGISTRY:
            continue
        mod = importlib.import_module(f"backend.blocks.{name}")
        register_block(mod.SCHEMA, mod.handler)
    yield


@pytest.fixture(autouse=True)
def headless_env(monkeypatch, tmp_path):
    """每个用例：无头模式 + 独立数据目录 + 干净 bridge 状态。"""
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "nxdata"))
    set_headless(True)
    mb._state.update(server=None, thread=None, token=None, api=None)
    yield
    mb.stop_mcp_bridge()
    set_headless(False)


@pytest.fixture
def server_api():
    from backend.server import ServerApi

    events: list[tuple[str, dict]] = []
    api = ServerApi(emit=lambda e, p: events.append((e, p)))
    api.events = events  # type: ignore[attr-defined]
    return api


def rpc(port: int, token: str, tool: str, args: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/rpc",
        method="POST",
        data=json.dumps({"tool": tool, "args": args or {}}).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# ServerApi 门面
# ---------------------------------------------------------------------------

def test_serverapi_list_flows_empty(server_api):
    out = server_api.list_flows()
    assert out["ok"] is True and out["flows"] == [] and out["exists"] is False


def test_serverapi_list_flows_picks_up_files(server_api, tmp_path):
    flows = server_api._flows_dir(create=True)
    (flows / "demo.flow.json").write_text(
        json.dumps({"name": "演示", "nodes": {}, "entry": ""}), encoding="utf-8"
    )
    out = server_api.list_flows()
    assert out["exists"] is True
    assert [f["name"] for f in out["flows"]] == ["演示"]


def test_serverapi_capture_desktop_rejected(server_api):
    out = server_api.capture_desktop()
    assert out["ok"] is False and "服务器形态无屏幕" in out["error"]


def test_serverapi_run_flow_validation_error(server_api):
    out = server_api.run_flow({"nodes": "not-a-dict", "entry": "a"})
    assert out["ok"] is False
    assert "nodes" in out["error"]


def test_serverapi_run_flow_screen_block_rejected_headless(server_api):
    flow = {
        "name": "坏流程",
        "nodes": {"a": {"type": "screenshot", "params": {}, "next": None}},
        "entry": "a",
    }
    out = server_api.run_flow(flow)
    assert out["ok"] is True  # 启动成功（拒绝发生在运行期）

    from backend.core.interpreter import get_interpreter

    get_interpreter().wait_until_idle(timeout=15)

    deadline = 5.0
    while deadline > 0 and not server_api._last_flow_finished:
        time.sleep(0.05)
        deadline -= 0.05
    finished = server_api._last_flow_finished or {}
    assert finished.get("ok") is False
    assert "需要真机桌面" in str(finished.get("error", ""))


# ---------------------------------------------------------------------------
# token 持久化
# ---------------------------------------------------------------------------

def test_resolve_token_persists_across_calls():
    from backend.paths import get_data_dir
    from backend.server import _resolve_token

    t1, source1 = _resolve_token("")
    assert source1 == "新生成（持久化文件）"
    token_path = get_data_dir() / "mcp" / "token"
    assert token_path.is_file()
    assert _resolve_token("")[0] == t1  # 重启进程 token 不变

    # --token-file 优先；再其次才是环境变量
    override = get_data_dir() / "override.token"
    override.write_text("fixed-secret\n", encoding="utf-8")
    assert _resolve_token(str(override)) == ("fixed-secret", "--token-file")


def test_resolve_token_env_precedence(monkeypatch):
    """NEXUZ_TOKEN env 优先于持久化文件（平台"自动密钥"注入路径）。"""
    from backend.server import _resolve_token

    monkeypatch.setenv("NEXUZ_TOKEN", "env-token-123")
    token, source = _resolve_token("")
    assert token == "env-token-123" and source == "NEXUZ_TOKEN env"


# ---------------------------------------------------------------------------
# 真实 bridge：start_mcp_bridge(host/port/token) + HTTP 闭环
# ---------------------------------------------------------------------------

@pytest.fixture
def live_bridge(server_api):
    assert mb.start_mcp_bridge(server_api, host="127.0.0.1", port=0, token="srv-token")
    status = mb.bridge_status()
    yield status["port"], server_api


def test_live_bridge_health(live_bridge):
    port, _api = live_bridge
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is True


def test_live_bridge_status_marks_headless(live_bridge):
    port, _api = live_bridge
    out = rpc(port, "srv-token", "get_status")
    assert out["ok"] is True
    assert out["result"]["headless"] is True


def test_live_bridge_list_blocks_filters_desktop(live_bridge):
    port, _api = live_bridge
    out = rpc(port, "srv-token", "list_blocks")
    types = {b["type"] for b in out["result"]["blocks"]}
    assert "click" not in types and "screenshot" not in types
    assert "browser_navigate" not in types and "clipboard" not in types
    assert "ocr_recognize" not in types
    assert "http_request" in types and "timestamp" in types


def test_live_bridge_run_block_timestamp_ok(live_bridge):
    port, _api = live_bridge
    out = rpc(port, "srv-token", "run_block", {"type": "timestamp", "params": {}})
    assert out["ok"] is True
    assert out["result"]["ok"] is True


def test_live_bridge_run_block_desktop_rejected(live_bridge):
    port, _api = live_bridge
    out = rpc(port, "srv-token", "run_block", {"type": "screenshot", "params": {}})
    assert out["result"]["ok"] is False
    assert "需要真机桌面" in out["result"]["error"]


def test_live_bridge_capture_screen_rejected(live_bridge):
    port, _api = live_bridge
    out = rpc(port, "srv-token", "capture_screen")
    assert out["result"]["ok"] is False
    assert "服务器形态无屏幕" in out["result"]["error"]


def test_live_bridge_run_flow_end_to_end(live_bridge):
    port, api = live_bridge
    flow = {
        "name": "时间戳流程",
        "nodes": {
            "a": {"type": "timestamp", "params": {}, "next": None},
        },
        "entry": "a",
    }
    out = rpc(port, "srv-token", "run_flow", {"flow": flow, "wait": True, "timeout_s": 15})
    body = out["result"]
    assert body["ok"] is True, body
    assert body["run"]["ok"] is True
    assert body["timed_out"] is False
    finished = body.get("finished") or {}
    assert finished.get("ok") is True
    # 流程结束事件进了通知汇（ServerApi emit → events 列表）
    event_names = [e for e, _p in api.events]  # type: ignore[attr-defined]
    assert "flow_finished" in event_names


def test_live_bridge_run_flow_desktop_flow_fails_with_clear_error(live_bridge):
    port, _api = live_bridge
    flow = {
        "name": "含真机积木",
        "nodes": {"a": {"type": "click", "params": {"x": 10, "y": 10}, "next": None}},
        "entry": "a",
    }
    out = rpc(port, "srv-token", "run_flow", {"flow": flow, "wait": True, "timeout_s": 15})
    body = out["result"]
    assert body["ok"] is True
    finished = body.get("finished") or {}
    assert finished.get("ok") is False
    assert "需要真机桌面" in str(finished.get("error", ""))
