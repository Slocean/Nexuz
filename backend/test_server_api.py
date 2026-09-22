"""服务器 /api 桥接与静态托管：白名单、鉴权、SPA 资源、ServerApi 方法面。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from backend.core import mcp_bridge as mb
from backend.core.host_mode import set_headless
from backend.core.registry import BLOCK_REGISTRY


@pytest.fixture(autouse=True)
def headless_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "nxdata"))
    set_headless(True)
    mb._state.update(server=None, thread=None, token=None, api=None)
    yield
    mb.stop_mcp_bridge()
    set_headless(False)


@pytest.fixture
def server_api():
    from backend.server import ServerApi

    return ServerApi()


@pytest.fixture
def live_bridge(server_api):
    assert mb.start_mcp_bridge(server_api, host="127.0.0.1", port=0, token="tok")
    port = mb.bridge_status()["port"]
    yield port, server_api
    set_headless(True)


def api_call(port: int, method: str, args: list | None = None, token: str = "tok") -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/{method}",
        method="POST",
        data=json.dumps({"args": args or []}).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(port: int, path: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, "", exc.read()


# ---------------------------------------------------------------------------
# /api 白名单与鉴权
# ---------------------------------------------------------------------------

def test_api_open_without_token(live_bridge):
    port, _api = live_bridge
    status, body = api_call(port, "list_flows", token=None)
    assert status == 200 and body["ok"] is True
    status, body = api_call(port, "list_flows", token="wrong")
    assert status == 200 and body["ok"] is True


def test_api_whitelisted_method_works(live_bridge):
    port, _api = live_bridge
    status, body = api_call(port, "list_flows")
    assert status == 200 and body["ok"] is True
    assert body["result"]["ok"] is True


def test_api_non_whitelisted_404(live_bridge):
    port, _api = live_bridge
    for method in ("pick_flow_file", "start_recording", "window_close", "no_such_method"):
        status, body = api_call(port, method)
        assert status == 404, method
        assert "服务器不提供方法" in body["error"]


def test_api_desktop_mode_404(live_bridge):
    """桌面模式（非无头）下 /api 整体不可用：桌面行为零变化。"""
    port, _api = live_bridge
    set_headless(False)
    try:
        status, _body = api_call(port, "list_flows")
        assert status == 404
    finally:
        set_headless(True)


def test_api_args_positional(live_bridge):
    port, api = live_bridge
    flows = api._flows_dir(create=True)
    (flows / "demo.flow.json").write_text(
        json.dumps({"name": "演示", "nodes": {}, "entry": ""}), encoding="utf-8"
    )
    status, body = api_call(port, "load_flow", [str(flows / "demo.flow.json")])
    assert status == 200 and body["result"]["ok"] is True
    assert body["result"]["flow"]["name"] == "演示"


# ---------------------------------------------------------------------------
# 静态托管（frontend/dist）
# ---------------------------------------------------------------------------

def test_static_serves_spa(live_bridge, monkeypatch, tmp_path):
    port, _api = live_bridge
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Nexuz Web</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(mb, "_dist_dir", lambda: dist)

    status, ctype, body = get(port, "/")
    assert status == 200 and "text/html" in ctype and b"Nexuz Web" in body
    status, ctype, _ = get(port, "/assets/app.js")
    assert status == 200 and "javascript" in ctype
    # SPA 回退：未知路径回 index.html
    status, ctype, body = get(port, "/some/route")
    assert status == 200 and b"Nexuz Web" in body


def test_static_blocks_traversal(live_bridge, monkeypatch, tmp_path):
    port, _api = live_bridge
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(mb, "_dist_dir", lambda: dist)

    status, _ctype, _body = get(port, "/../secret.txt")
    assert status != 200 or b"secret" not in (get(port, "/../secret.txt")[2])


def test_static_missing_dist_404(live_bridge, monkeypatch, tmp_path):
    port, _api = live_bridge
    monkeypatch.setattr(mb, "_dist_dir", lambda: tmp_path / "nope")
    status, _ctype, _body = get(port, "/")
    assert status == 404


# ---------------------------------------------------------------------------
# ServerApi 方法面
# ---------------------------------------------------------------------------

def test_serverapi_flow_library_crud(server_api):
    saved = server_api.save_flow(json.dumps({"name": "测试", "nodes": {}, "entry": ""}))
    assert saved["ok"] is True
    listed = server_api.list_flows()
    assert [f["name"] for f in listed["flows"]] == ["测试"]
    loaded = server_api.load_flow(saved["path"])
    assert loaded["ok"] is True and loaded["flow"]["name"] == "测试"
    dup = server_api.duplicate_flow(saved["path"])
    assert dup["ok"] is True and dup["path"] != saved["path"]
    renamed = server_api.rename_flow(saved["path"], "改名")
    assert renamed["ok"] is True
    deleted = server_api.delete_flow(saved["path"])
    assert deleted["ok"] is True
    assert len(server_api.list_flows()["flows"]) == 1


def test_serverapi_save_flow_rejects_outside(server_api, tmp_path):
    outside = tmp_path / "evil.flow.json"
    out = server_api.save_flow(json.dumps({"name": "x", "nodes": {}, "entry": ""}), str(outside))
    # 库外路径按名称落到库内，而不是写库外
    assert out["ok"] is True
    assert str(server_api._flows_dir()) in out["path"]


def test_serverapi_is_running_and_validate(server_api):
    running = server_api.is_running()
    assert running["ok"] is True and running["running"] is False
    assert server_api.validate_flow(json.dumps({"nodes": {}, "entry": ""}))["ok"] is True
    assert server_api.validate_flow("not-json")["ok"] is False


def test_serverapi_schedule_jobs(server_api):
    out = server_api.list_schedule_jobs()
    assert out["ok"] is True and isinstance(out["jobs"], list)


def test_serverapi_drain_ui_events(server_api):
    server_api._emit("node_start", {"node_id": "a"})
    out = server_api.drain_ui_events()
    assert out["ok"] is True and len(out["messages"]) == 1
    assert out["messages"][0]["event"] == "node_start"
    assert server_api.drain_ui_events()["messages"] == []


def test_serverapi_block_registry_headless_filtered(server_api):
    from backend.core.registry import register_all_blocks

    register_all_blocks()
    schemas = server_api.get_block_registry()
    types = {s.get("type") for s in schemas}
    assert "click" not in types  # requires=desktop 被过滤
    assert "browser_navigate" not in types
    assert "clipboard" not in types
    assert "ocr_recognize" not in types
    assert "http_request" in types
    assert "llm_forward" in types
    assert "image_generate" in types


def test_serverapi_ui_settings_roundtrip(server_api):
    out = server_api.set_ui_settings({"themeName": "Night"})
    assert out["settings"]["themeName"] == "Night"
    assert server_api.get_ui_settings()["settings"]["themeName"] == "Night"


def test_serverapi_run_flow_end_to_end(server_api):
    flow = {
        "name": "e2e",
        "nodes": {"a": {"type": "timestamp", "params": {}, "next": None}},
        "entry": "a",
    }
    out = server_api.run_flow(flow)
    assert out["ok"] is True and out["started"] is True
    from backend.core.interpreter import get_interpreter

    get_interpreter().wait_until_idle(timeout=15)
    assert server_api.is_running()["running"] is False
