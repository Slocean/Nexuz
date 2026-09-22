"""API Key 分能力凭证：CRUD、双身份鉴权、scope 闸、积木白名单（/api 与 /rpc）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from backend.core import api_keys
from backend.core import mcp_bridge as mb
from backend.core.host_mode import set_headless
from backend.core.registry import BLOCK_REGISTRY


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "nxdata"))
    set_headless(True)
    mb._state.update(server=None, thread=None, token=None, api=None)
    mb._run_ctx.update(context={}, counter=0)  # 不污染共享会话上下文
    if "smtp_send" not in BLOCK_REGISTRY:
        from backend.core.registry import register_all_blocks

        register_all_blocks()
    yield
    mb._run_ctx.update(context={}, counter=0)
    mb.stop_mcp_bridge()
    set_headless(False)


@pytest.fixture
def server_api():
    from backend.server import ServerApi

    return ServerApi()


@pytest.fixture
def live_bridge(server_api):
    assert mb.start_mcp_bridge(server_api, host="127.0.0.1", port=0, token="master-tok")
    port = mb.bridge_status()["port"]
    yield port
    set_headless(True)


def request_json(port: int, path: str, token: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture
def scoped_key(server_api):
    """已签发：仅 catalog + run_block + flows，积木白名单 [smtp_send, timestamp]。"""
    out = server_api.apikey_create(
        {
            "name": "日报程序",
            "scopes": ["catalog", "run_block", "flows"],
            "block_allowlist": ["smtp_send", "timestamp"],
        }
    )
    assert out["ok"] is True
    return out["key"]  # 含明文 key（仅此一次）


# ---------------------------------------------------------------------------
# CRUD 与哈希存储
# ---------------------------------------------------------------------------

def test_create_stores_hash_not_plaintext(server_api, scoped_key):
    assert scoped_key["key"].startswith("nxz_")
    raw = server_api.apikey_list()
    stored = raw["keys"][0]
    assert "key_hash" not in stored and "key" not in stored
    assert stored["key_prefix"] == scoped_key["key"][:10]
    assert stored["name"] == "日报程序"
    assert set(stored["scopes"]) == {"catalog", "run_block", "flows"}


def test_authenticate_and_disable(server_api, scoped_key):
    rec = api_keys.authenticate(scoped_key["key"])
    assert rec is not None and rec["id"] == scoped_key["id"]
    assert api_keys.authenticate("nxz_wrong-key-value-000") is None
    assert api_keys.authenticate("not-a-key") is None

    server_api.apikey_update(scoped_key["id"], {"enabled": False})
    assert api_keys.authenticate(scoped_key["key"]) is None
    server_api.apikey_update(scoped_key["id"], {"enabled": True})
    assert api_keys.authenticate(scoped_key["key"]) is not None

    assert server_api.apikey_delete(scoped_key["id"])["ok"] is True
    assert api_keys.authenticate(scoped_key["key"]) is None


def test_unknown_scopes_dropped(server_api):
    out = server_api.apikey_create({"name": "x", "scopes": ["catalog", "hacker"], "block_allowlist": ["a"]})
    assert out["ok"] is True
    assert out["key"]["scopes"] == ["catalog"]


# ---------------------------------------------------------------------------
# HTTP 层：无头服务器不验凭证（门外由部署网关管）
# ---------------------------------------------------------------------------

def test_api_open_without_token(live_bridge):
    status, body = request_json(live_bridge, "/api/list_flows", "", {"args": []})
    assert status == 200 and body["result"]["ok"] is True


def test_api_open_ignores_scoped_key(live_bridge, scoped_key):
    key = scoped_key["key"]
    status, body = request_json(live_bridge, "/api/list_schedule_jobs", key, {"args": []})
    assert status == 200 and body["result"]["ok"] is True
    status, body = request_json(live_bridge, "/api/apikey_list", key, {"args": []})
    assert status == 200 and body["result"]["ok"] is True


def test_run_block_via_api_still_gates_dangerous(live_bridge):
    status, body = request_json(
        live_bridge, "/api/run_block", "", {"args": [{"type": "timestamp", "params": {}}]}
    )
    assert status == 200 and body["result"]["ok"] is True
    status, body = request_json(
        live_bridge, "/api/run_block", "", {"args": [{"type": "run_command", "params": {}}]}
    )
    assert status == 200 and body["result"]["ok"] is False
    assert "不支持 AI 实时执行" in body["result"]["error"]


def test_rpc_open_without_token(live_bridge):
    status, body = request_json(live_bridge, "/rpc", "", {"tool": "list_schedules", "args": {}})
    assert status == 200 and body["result"]["ok"] is True
    out = mb.dispatch(type("Api", (), {})(), "list_schedules", {})
    assert out["ok"] is True
