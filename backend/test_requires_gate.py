"""requires 分档闸：C 档拒绝、B 档按参数判定、目录过滤与 schema 报错。

覆盖 host_mode.headless_block_error、run_block_once、tool_catalog、
mcp_bridge.dispatch（capture_screen 短路）四条路径。
"""

from __future__ import annotations

import importlib

import pytest

from backend.core import host_mode
from backend.core.ai import tool_catalog
from backend.core.ai.run_block import run_block_once
from backend.core.host_mode import headless_block_error, set_headless
from backend.core.registry import BLOCK_REGISTRY, register_block


def _ensure_real_blocks() -> None:
    """确保 27 个分档积木在注册表里（其他测试模块可能 pop 过同名真实积木，
    如 test_monitor 的 schema 校验用例；只补缺，不做全量重注册以免清掉他人
    的测试积木）。"""
    for name in DESKTOP_BLOCK_TYPES | PARTIAL_BLOCK_TYPES:
        if name in BLOCK_REGISTRY:
            continue
        mod = importlib.import_module(f"backend.blocks.{name}")
        register_block(mod.SCHEMA, mod.handler)


@pytest.fixture(autouse=True)
def _blocks_registered():
    _ensure_real_blocks()
    yield


@pytest.fixture(autouse=True)
def _headless_off_by_default():
    set_headless(False)
    yield
    set_headless(False)


# ---------------------------------------------------------------------------
# 标记本身
# ---------------------------------------------------------------------------

DESKTOP_BLOCK_TYPES = {
    "click", "drag", "key_press", "mouse_hover", "mouse_scroll", "type_text",
    "screenshot", "color_detect", "find_image", "locate_text", "if_color_match",
    "window_activate", "window_close", "window_wait",
    "notify", "volume_action", "power_action",
}
PARTIAL_BLOCK_TYPES = {
    "clipboard", "delay", "monitor_start", "monitor_check", "monitor_wait",
    "monitor_list", "monitor_stop", "open_path", "system_info", "wait_until",
}


def test_desktop_blocks_marked():
    for btype in DESKTOP_BLOCK_TYPES:
        schema = (BLOCK_REGISTRY.get(btype) or {}).get("schema") or {}
        assert schema.get("requires") == "desktop", btype


def test_partial_blocks_marked():
    for btype in PARTIAL_BLOCK_TYPES:
        schema = (BLOCK_REGISTRY.get(btype) or {}).get("schema") or {}
        assert schema.get("requires") == "partial", btype


def test_desktop_mode_allows_everything():
    for btype in DESKTOP_BLOCK_TYPES | PARTIAL_BLOCK_TYPES:
        assert headless_block_error(btype, {}) is None, btype


# ---------------------------------------------------------------------------
# headless_block_error：C 档一律拒，B 档按参数
# ---------------------------------------------------------------------------

def test_headless_rejects_desktop_tier():
    set_headless(True)
    for btype in DESKTOP_BLOCK_TYPES:
        err = headless_block_error(btype, {})
        assert err is not None and "需要真机桌面" in err, btype


def test_headless_wait_until_by_param():
    set_headless(True)
    assert headless_block_error("wait_until", {"wait_type": "expression"}) is None
    assert headless_block_error("wait_until", {"wait_type": "color"}) is not None
    # 缺省 wait_type=text（屏幕条件）→ 拒
    assert headless_block_error("wait_until", {}) is not None


def test_headless_monitor_start_by_param():
    set_headless(True)
    assert headless_block_error("monitor_start", {"monitor_type": "process"}) is None
    assert headless_block_error("monitor_start", {"monitor_type": "file"}) is None
    for mtype in ("window", "screen_text", "screen_color"):
        assert headless_block_error("monitor_start", {"monitor_type": mtype}) is not None


def test_headless_unknown_block_allowed():
    set_headless(True)
    assert headless_block_error("no_such_block", {}) is None


# ---------------------------------------------------------------------------
# run_block_once 闸
# ---------------------------------------------------------------------------

def _run_ctx() -> dict:
    return {"context": {}, "counter": 0}


def test_run_block_once_headless_rejects_desktop_tier():
    set_headless(True)
    result = run_block_once({"type": "screenshot", "params": {}}, run_ctx=_run_ctx())
    assert result["ok"] is False
    assert "需要真机桌面" in result["error"]


def test_run_block_once_headless_rejects_screen_wait():
    set_headless(True)
    result = run_block_once(
        {"type": "wait_until", "params": {"wait_type": "text", "region": [0, 0, 10, 10]}},
        run_ctx=_run_ctx(),
    )
    assert result["ok"] is False
    assert "wait_until" in result["error"]


# ---------------------------------------------------------------------------
# tool_catalog：无头目录裁剪与 schema 报错
# ---------------------------------------------------------------------------

def test_catalog_hides_desktop_tier_headless():
    types_desktop = {t["type"] for t in tool_catalog.list_blocks(allow_dangerous=True)}
    assert "click" in types_desktop and "screenshot" in types_desktop

    set_headless(True)
    types_headless = {t["type"] for t in tool_catalog.list_blocks(allow_dangerous=True)}
    assert DESKTOP_BLOCK_TYPES.isdisjoint(types_headless)
    assert PARTIAL_BLOCK_TYPES <= types_headless
    partial = next(t for t in tool_catalog.list_blocks() if t["type"] == "wait_until")
    assert "服务器形态" in partial["description"]


def test_get_block_schema_headless_error():
    set_headless(True)
    out = tool_catalog.get_block_schema("click", allow_dangerous=True)
    assert "error" in out and "需要真机桌面" in out["error"]


def test_desktop_mode_catalog_untouched():
    """桌面模式零变化：真机积木在目录里、无服务器后缀文案。"""
    types = {t["type"] for t in tool_catalog.list_blocks(allow_dangerous=True)}
    assert DESKTOP_BLOCK_TYPES <= types and PARTIAL_BLOCK_TYPES <= types
    partial = next(t for t in tool_catalog.list_blocks() if t["type"] == "wait_until")
    assert "服务器形态" not in partial["description"]


# ---------------------------------------------------------------------------
# mcp_bridge.dispatch：无头屏幕工具短路（带 host_mode 注入，验证 get_status 标记）
# ---------------------------------------------------------------------------

def test_dispatch_headless_capture_screen_short_circuit(monkeypatch):
    from backend.core import mcp_bridge as mb

    set_headless(True)
    out = mb.dispatch(type("Api", (), {})(), "capture_screen", {})
    assert out["ok"] is False
    assert "服务器形态无屏幕" in out["error"]

    out = mb.dispatch(type("Api", (), {})(), "locate_text_on_screen", {"match_text": "x"})
    assert out["ok"] is False
    assert "服务器形态无屏幕" in out["error"]


def test_headless_flag_roundtrip():
    assert host_mode.is_headless() is False
    set_headless(True)
    assert host_mode.is_headless() is True
    set_headless(False)
    assert host_mode.is_headless() is False
