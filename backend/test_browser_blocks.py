"""browser_* 积木：引擎注入、错误转 ok=False、等待轮询、run_block 安全闸。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import browser as bmod
from backend.core.browser import session as bsession
from backend.core.browser.discovery import parse_devtools_port_file
from backend.core.browser.engine import BrowserEngine
from backend.core.browser.errors import BrowserError, BrowserTimeoutError
from backend.core.ai import run_block as rb
from backend.core.registry import register_all_blocks


class FakeEngine(BrowserEngine):
    """Canned engine: records calls, returns scripted values."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.alive = True
        self.eval_values: dict[str, object] = {}
        self.viewport = {"width": 1280, "height": 800}

    def _rec(self, name, *args):
        self.calls.append((name, *args))

    def launch(self, *, headless, user_data_dir, binary_path=""):
        self._rec("launch", headless)
        self.launched = True

    def close(self):
        self._rec("close")
        self.alive = False

    def is_alive(self):
        return self.alive

    def navigate(self, url, timeout_ms=30000):
        self._rec("navigate", url)
        url = str(url)
        if "://" not in url:
            url = "https://" + url
        if url == "boom://fail":
            raise BrowserError("导航失败")
        return {"url": url, "title": f"标题:{url}"}

    def current_url(self):
        return "https://example.com/"

    def title(self):
        return "Example Domain"

    def set_viewport(self, width, height):
        self._rec("set_viewport", width, height)
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError("视口尺寸必须是正数（像素）")
        self.viewport = {"width": width, "height": height}
        return dict(self.viewport)

    def viewport_size(self):
        return dict(self.viewport)

    def quick_status(self):
        return {"url": self.current_url(), "title": self.title(), "tabs": 1}

    def list_tabs(self):
        return [{"title": self.title(), "url": self.current_url()}]

    def eval_js(self, expression, timeout_ms=15000):
        self._rec("eval", expression)
        for key, value in self.eval_values.items():
            if key in expression:
                return value
        return None

    def extract(self, selector, attr="", max_items=200):
        self._rec("extract", selector)
        if selector == "missing":
            raise BrowserError(f"未找到元素: {selector}")
        return [
            {"text": "Hello", "value": None, "href": "https://x/", "attr": None,
             "rect": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0}}
        ]

    def click(self, selector, timeout_ms=10000, use_js=False):
        self._rec("click", selector, use_js)
        if selector == "missing":
            raise BrowserError(f"未找到元素: {selector}")
        return {"x": 10.0, "y": 20.0}

    def fill(self, selector, text, timeout_ms=10000):
        self._rec("fill", selector, text)
        if selector == "missing":
            raise BrowserError(f"未找到元素: {selector}")
        return {"ok": True}

    def screenshot(self, save_path=None, full_page=True, clip=None):
        self._rec("screenshot", save_path, full_page, clip)
        Path(save_path).write_bytes(b"png")
        vp = self.viewport_size()
        if clip:
            width, height = int(round(clip["width"])), int(round(clip["height"]))
        else:
            width, height = 800, 600
        return {
            "path": save_path,
            "width": width,
            "height": height,
            "viewport_width": vp["width"],
            "viewport_height": vp["height"],
        }

    def wait_document(self, state, timeout_ms=30000):
        self._rec("wait_document", state)
        return {"ready_state": state, "url": self.current_url()}


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(bsession, "get_engine", lambda: engine)
    monkeypatch.setattr(bsession, "_engine", engine)
    monkeypatch.setattr(
        bsession,
        "get_browser_config",
        lambda: {"engine": "cdp", "headless": True, "keep_alive": False, "profile_dir": "", "edge_path": ""},
    )
    yield engine


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


# ── 积木层 ────────────────────────────────────────────────────────────


def test_navigate_ok(fake_engine):
    from backend.blocks.browser_navigate import handler

    out = handler({"url": "example.com"}, {})
    assert out["ok"] is True
    assert out["url"] == "https://example.com"
    assert out["title"] == "标题:https://example.com"


def test_navigate_error_to_ok_false(fake_engine):
    from backend.blocks.browser_navigate import handler

    out = handler({"url": "boom://fail"}, {})
    assert out["ok"] is False
    assert "导航失败" in out["error"]


def test_extract_and_click_and_fill(fake_engine):
    from backend.blocks.browser_click import handler as click
    from backend.blocks.browser_extract import handler as extract
    from backend.blocks.browser_fill import handler as fill

    out = extract({"selector": ".item"}, {})
    assert out["ok"] is True and out["count"] == 1 and out["items"][0]["text"] == "Hello"
    assert click({"selector": "#go"}, {})["ok"] is True
    assert fill({"selector": "#q", "text": "hi"}, {})["ok"] is True
    assert extract({"selector": "missing"}, {})["ok"] is False


def test_screenshot_ok(fake_engine, tmp_path):
    from backend.blocks.browser_screenshot import handler

    target = tmp_path / "page.png"
    out = handler({"save_path": str(target), "full_page": True}, {})
    assert out["ok"] is True and out["width"] == 800 and out["height"] == 600
    assert out["viewport_width"] == 1280 and out["viewport_height"] == 800
    assert Path(out["path"]).exists()


def test_resize_ok_and_invalid(fake_engine):
    from backend.blocks.browser_resize import handler

    out = handler({"width": 1366, "height": 768}, {})
    assert out["ok"] is True and out["width"] == 1366 and out["height"] == 768
    assert ("set_viewport", 1366, 768) in fake_engine.calls

    fake_engine.calls.clear()
    out = handler({"width": 0, "height": 768}, {})
    assert out["ok"] is False and "正数" in out["error"]


def test_navigate_with_viewport(fake_engine):
    from backend.blocks.browser_navigate import handler

    out = handler({"url": "example.com", "viewport_width": 1280, "viewport_height": 800}, {})
    assert out["ok"] is True
    names = [c[0] for c in fake_engine.calls]
    assert names == ["navigate", "set_viewport"]

    fake_engine.calls.clear()
    out = handler({"url": "example.com"}, {})
    assert out["ok"] is True
    assert [c[0] for c in fake_engine.calls] == ["navigate"]

    fake_engine.calls.clear()
    # 参数不配对：导航前即失败，不产生导航副作用
    with pytest.raises(ValueError, match="同时"):
        handler({"url": "example.com", "viewport_width": 1280}, {})
    assert fake_engine.calls == []


def test_screenshot_clip_rect(fake_engine, tmp_path):
    from backend.blocks.browser_screenshot import handler

    target = str(tmp_path / "clip.png")
    out = handler({"save_path": target, "clip": [10, 20, 110, 120]}, {})
    assert out["ok"] is True and out["width"] == 100 and out["height"] == 100
    assert ("screenshot", target, True, {"x": 10.0, "y": 20.0, "width": 100.0, "height": 100.0}) in fake_engine.calls


def test_screenshot_clip_selector(fake_engine, tmp_path):
    from backend.blocks.browser_screenshot import handler

    fake_engine.eval_values = {
        "scrollX": {
            "doc": {"x": 0.0, "y": 50.0, "width": 200.0, "height": 100.0},
            "vp": {"x": 0.0, "y": -50.0, "width": 200.0, "height": 100.0},
        }
    }
    target = str(tmp_path / "el.png")
    out = handler({"save_path": target, "full_page": True, "clip_selector": "#card"}, {})
    assert out["ok"] is True and out["width"] == 200 and out["height"] == 100
    assert ("screenshot", target, True, {"x": 0.0, "y": 50.0, "width": 200.0, "height": 100.0}) in fake_engine.calls

    # 视口模式用视口坐标
    fake_engine.calls.clear()
    out = handler({"save_path": target, "full_page": False, "clip_selector": "#card"}, {})
    assert out["ok"] is True
    assert ("screenshot", target, False, {"x": 0.0, "y": -50.0, "width": 200.0, "height": 100.0}) in fake_engine.calls


def test_screenshot_clip_conflict_and_invalid(fake_engine, tmp_path):
    from backend.blocks.browser_screenshot import handler

    target = str(tmp_path / "x.png")
    with pytest.raises(ValueError, match="二选一"):
        handler({"save_path": target, "clip": [0, 0, 10, 10], "clip_selector": "#a"}, {})
    with pytest.raises(ValueError, match="无效"):
        handler({"save_path": target, "clip": [10, 10, 10, 10]}, {})


def test_eval_passthrough(fake_engine):
    from backend.blocks.browser_eval import handler

    fake_engine.eval_values = {"1 + 1": 2}
    out = handler({"expression": "1 + 1"}, {})
    assert out["ok"] is True and out["result"] == 2


def test_browser_snapshot_and_ref_actions(fake_engine):
    from backend.blocks import browser_snapshot as snap
    from backend.blocks.browser_click import handler as click
    from backend.blocks.browser_fill import handler as fill
    from backend.blocks.browser_navigate import handler as navigate

    fake_engine.eval_values = {"nth-of-type": {
        "url": "https://example.com/", "title": "Example Domain",
        "items": [
            {"selector": "#go", "tag": "button", "text": "go", "placeholder": None,
             "value": None, "href": None, "rect": {"x": 1, "y": 2, "width": 30, "height": 20}},
            {"selector": "body > a:nth-of-type(2)", "tag": "a", "text": "hidden", "placeholder": None,
             "value": None, "href": "#", "rect": {"x": 0, "y": 0, "width": 0, "height": 0}},
        ],
    }}
    out = snap.handler({}, {})
    assert out["ok"] is True and out["count"] == 1  # 零尺寸元素被过滤
    assert out["elements"][0]["ref"] == "e1"
    assert rb.classify_run_block("browser_snapshot") == "safe"

    out = click({"ref": "e1"}, {})
    assert out["ok"] is True and ("click", "#go", False) in fake_engine.calls

    fake_engine.calls.clear()
    out = fill({"ref": "e1", "text": "hi"}, {})
    assert out["ok"] is True and ("fill", "#go", "hi") in fake_engine.calls

    # 显式 selector 优先于 ref
    fake_engine.calls.clear()
    out = click({"selector": "#other", "ref": "e1"}, {})
    assert out["ok"] is True and ("click", "#other", False) in fake_engine.calls

    # 快照清空 / 页面导航后 ref 失效
    snap.clear_refs(fake_engine)
    out = click({"ref": "e1"}, {})
    assert out["ok"] is False and "browser_snapshot" in out["error"]

    fake_engine.eval_values = {"nth-of-type": {"url": "", "title": "", "items": [
        {"selector": "#go", "tag": "button", "text": "go", "placeholder": None,
         "value": None, "href": None, "rect": {"x": 1, "y": 2, "width": 30, "height": 20}},
    ]}}
    snap.handler({}, {})
    navigate({"url": "example.com"}, {})
    out = click({"ref": "e1"}, {})
    assert out["ok"] is False


def test_close_forces(fake_engine):
    from backend.blocks.browser_close import handler

    out = handler({}, {})
    assert out["ok"] is True
    assert fake_engine.alive is False


def test_browser_tabs_and_session_status(fake_engine, monkeypatch):
    from backend.blocks.browser_tabs import handler

    out = handler({}, {})
    assert out["ok"] is True and out["count"] == 1
    assert out["tabs"][0]["url"] == "https://example.com/"
    assert rb.classify_run_block("browser_tabs") == "safe"

    # alive 时 session_status 附 quick_status 摘要（url/title/tabs）
    monkeypatch.setattr(bsession, "_signature", ("cdp", True, "", ""))
    st = bsession.session_status()
    assert st["alive"] is True and st["engine"] == "cdp"
    assert st["url"] == "https://example.com/" and st["tabs"] == 1
    assert st["title"] == "Example Domain"


def test_wait_success_and_timeout(fake_engine):
    from backend.blocks.browser_wait import handler as wait

    fake_engine.eval_values = {"document.querySelector": True}
    out = wait({"wait_type": "selector", "target": ".ok", "timeout_ms": 2000, "poll_ms": 50}, {})
    assert out["ok"] is True

    fake_engine.eval_values = {"document.querySelector": False}
    with pytest.raises(TimeoutError):
        wait({"wait_type": "selector", "target": ".ok", "timeout_ms": 300, "poll_ms": 50}, {})


def test_wait_stop_interrupts():
    from backend.blocks.browser_wait import handler as wait

    with pytest.raises(InterruptedError):
        wait(
            {"wait_type": "selector", "target": ".ok", "timeout_ms": 5000, "poll_ms": 50},
            {},
            should_stop=lambda: True,
        )


# ── run_block 安全闸 ──────────────────────────────────────────────────


def test_run_block_gate_safe_vs_action(fake_engine):
    # 主开关未开 → 拒绝
    out = rb.run_block_once({"type": "browser_extract", "params": {"selector": ".a"}}, run_ctx={})
    assert out["ok"] is False and "未开启" in out["error"]

    # SAFE：仅 allow_run_block 即可
    out = rb.run_block_once(
        {"type": "browser_extract", "params": {"selector": ".a"}},
        run_ctx={},
        allow_run_block=True,
    )
    assert out["ok"] is True and out["tier"] == "safe"

    # ACTION：navigate 需要 allow_dangerous
    out = rb.run_block_once(
        {"type": "browser_navigate", "params": {"url": "https://example.com"}},
        run_ctx={},
        allow_run_block=True,
    )
    assert out["ok"] is False and "危险模式" in out["error"]

    out = rb.run_block_once(
        {"type": "browser_navigate", "params": {"url": "https://example.com"}},
        run_ctx={},
        allow_run_block=True,
        allow_dangerous=True,
    )
    assert out["ok"] is True and out["tier"] == "action"

    # eval 同为 ACTION
    assert rb.classify_run_block("browser_eval") == "action"
    # resize 为 ACTION，close 为 SAFE
    assert rb.classify_run_block("browser_resize") == "action"
    assert rb.classify_run_block("browser_close") == "safe"


def test_run_block_unknown_browser_type_denied(fake_engine):
    assert rb.classify_run_block("browser_foo") is None


# ── 纯函数 ────────────────────────────────────────────────────────────


def test_parse_devtools_port_file(tmp_path):
    target = tmp_path / "DevToolsActivePort"
    target.write_text("9222\ndevtools/browser/abc-123\n", encoding="utf-8")
    port, ws_path = parse_devtools_port_file(tmp_path)
    assert port == 9222
    assert ws_path == "devtools/browser/abc-123"
    with pytest.raises(FileNotFoundError):
        parse_devtools_port_file(tmp_path / "nope")


def test_browser_config_roundtrip(monkeypatch):
    store: dict = {}

    def fake_load():
        return dict(store)

    def fake_save(cfg):
        store.clear()
        store.update(cfg)

    monkeypatch.setattr("backend.paths.load_app_config", fake_load)
    monkeypatch.setattr("backend.paths.save_app_config", fake_save)

    cfg = bmod.get_browser_config()
    assert cfg["engine"] == "auto" and cfg["headless"] is True

    saved = bmod.set_browser_config({"engine": "drission", "headless": False, "keep_alive": True})
    assert saved["engine"] == "drission"
    assert saved["headless"] is False and saved["keep_alive"] is True

    # 非法引擎名忽略
    saved = bmod.set_browser_config({"engine": "bogus"})
    assert saved["engine"] == "drission"


def test_session_status_never_launches(monkeypatch):
    def boom():
        raise AssertionError("session_status 不应拉起浏览器")

    monkeypatch.setattr(bsession, "get_engine", boom)
    st = bsession.session_status()
    assert st == {"alive": False, "engine": None}


def test_engine_resolution_auto(monkeypatch):
    monkeypatch.setattr(bmod, "get_browser_config", lambda: {"engine": "auto", "headless": True, "keep_alive": False, "profile_dir": "", "edge_path": ""})
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "DrissionPage" else __import__("importlib.util", fromlist=["x"]).find_spec(name))
    name = bsession._resolve_engine_name({"engine": "auto"})
    assert name == "cdp"


# ── 真实 Edge 冒烟（NEXUZ_BROWSER_E2E=1 时启用）─────────────────────


def _edge_available() -> bool:
    from backend.core.browser.discovery import find_browser

    return bool(find_browser())


@pytest.mark.skipif(
    not _edge_available() or __import__("os").environ.get("NEXUZ_BROWSER_E2E") != "1",
    reason="需要本机 Edge 且 NEXUZ_BROWSER_E2E=1",
)
def test_real_edge_smoke(tmp_path):
    from urllib.parse import quote

    from backend.core.browser.cdp_backend import CdpEngine

    html = (
        "<html><head><title>nxE2E</title></head><body>"
        "<h1 class='t'>hi e2e</h1>"
        "<input id='q' value=''/>"
        "<button id='b' onclick=\"document.getElementById('q').setAttribute('data-clicked','1')\">go</button>"
        "</body></html>"
    )
    url = "data:text/html;charset=utf-8," + quote(html)
    eng = CdpEngine()
    eng.launch(headless=True, user_data_dir=tmp_path / "profile")
    try:
        page = eng.navigate(url)
        assert page["title"] == "nxE2E"
        vp = eng.set_viewport(1024, 700)
        assert vp["width"] == 1024 and vp["height"] == 700
        size = eng.viewport_size()
        assert size["width"] == 1024 and size["height"] == 700
        assert eng.eval_js("window.innerWidth") == 1024
        assert eng.eval_js("window.innerHeight") == 700
        assert eng.eval_js("document.querySelector('.t').textContent") == "hi e2e"
        items = eng.extract(".t")
        assert items and items[0]["text"] == "hi e2e"
        assert eng.fill("#q", "hello")["ok"] is True
        assert eng.eval_js("document.getElementById('q').value") == "hello"
        pos = eng.click("#b")
        assert pos["x"] > 0 and pos["y"] > 0
        assert eng.eval_js("document.getElementById('q').getAttribute('data-clicked')") == "1"
        from backend.blocks.browser_snapshot import _SNAPSHOT_JS

        snap = eng.eval_js(_SNAPSHOT_JS.replace("__MAX__", "200"))
        selectors = {i["selector"] for i in snap["items"]}
        assert "#b" in selectors and "#q" in selectors
        shot = eng.screenshot(save_path=str(tmp_path / "s.png"), full_page=True)
        assert Path(shot["path"]).stat().st_size > 0
        assert shot["viewport_width"] == 1024 and shot["viewport_height"] == 700
        clip_shot = eng.screenshot(
            save_path=str(tmp_path / "c.png"),
            full_page=True,
            clip={"x": 0, "y": 0, "width": 120, "height": 60},
        )
        assert (clip_shot["width"], clip_shot["height"]) == (120, 60)
    finally:
        eng.close()
    assert not eng.is_alive()


def test_timeout_error_hierarchy():
    assert issubclass(BrowserTimeoutError, BrowserError)
