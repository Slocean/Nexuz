"""Chromium DevTools Protocol backend driven over websockets.sync.

Launches Edge/Chrome with --remote-debugging-port=0, resolves the ws endpoint
via DevToolsActivePort + /json/list, then drives the page with a single pump
thread (all ws send/recv happens there; command threads wait on events).
Click/fill/extract are implemented by injecting JS through Runtime.evaluate;
click defaults to Input.dispatchMouseEvent for isTrusted events.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import itertools
import json
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from backend.core.browser.discovery import find_browser, parse_devtools_port_file
from backend.core.browser.engine import BrowserEngine, element_record
from backend.core.browser.errors import (
    BrowserError,
    BrowserEvalError,
    BrowserSessionClosedError,
    BrowserTimeoutError,
)

_WS_RECV_TIMEOUT = 0.5

_EXTRACT_JS = """
(() => {{
  const SEL = {sel}, ATTR = {attr}, MAX = {max};
  const nodes = document.querySelectorAll(SEL);
  const out = [];
  for (const el of Array.from(nodes).slice(0, MAX)) {{
    const r = el.getBoundingClientRect();
    out.push({{
      text: (el.innerText || el.textContent || '').trim().slice(0, 2000),
      value: ('value' in el) ? el.value : null,
      href: el.getAttribute ? el.getAttribute('href') : null,
      attr: ATTR && el.getAttribute ? el.getAttribute(ATTR) : null,
      rect: {{x: r.x, y: r.y, width: r.width, height: r.height}},
    }});
  }}
  return {{count: nodes.length, items: out}};
}})()
"""

_CLICK_CENTER_JS = """
(() => {{
  const SEL = {sel};
  const el = document.querySelector(SEL);
  if (!el) return {{found: false}};
  el.scrollIntoView({{block: 'center', inline: 'center'}});
  const r = el.getBoundingClientRect();
  return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2}};
}})()
"""

_JS_CLICK_JS = """
(() => {{
  const SEL = {sel};
  const el = document.querySelector(SEL);
  if (!el) return {{found: false}};
  el.scrollIntoView({{block: 'center', inline: 'center'}});
  el.click();
  return {{found: true}};
}})()
"""

_FILL_JS = """
(() => {{
  const SEL = {sel}, TEXT = {text};
  const el = document.querySelector(SEL);
  if (!el) return {{found: false}};
  el.scrollIntoView({{block: 'center'}});
  el.focus();
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : (el.isContentEditable ? el.constructor.prototype : HTMLInputElement.prototype);
  const setter = Object.getOwnPropertyDescriptor(proto, 'value');
  if (setter && setter.set) setter.set.call(el, TEXT);
  else el.textContent = TEXT;
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  return {{found: true}};
}})()
"""


def _js_str(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


class CdpEngine(BrowserEngine):
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._ws: Any = None
        self._user_data_dir: Path | None = None
        self._alive = False
        self._pump: threading.Thread | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, dict[str, Any]] = {}
        self._send_q: Queue[dict[str, Any]] = Queue()
        self._events: deque[dict[str, Any]] = deque(maxlen=512)
        self._pending_lock = threading.Lock()
        self._debug_port = 0

    # ── lifecycle ─────────────────────────────────────────────────────

    def launch(self, *, headless: bool, user_data_dir: Path, binary_path: str = "") -> None:
        if self.is_alive():
            return
        exe = find_browser(binary_path)
        if not exe:
            raise BrowserError("未找到 Edge/Chrome，请在设置中指定浏览器路径")
        user_data_dir.mkdir(parents=True, exist_ok=True)
        # A stale file would make us connect to a dead port.
        try:
            (user_data_dir / "DevToolsActivePort").unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        args = [
            exe,
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "about:blank",
        ]
        if headless:
            args.insert(2, "--headless=new")
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._proc = proc
        self._user_data_dir = user_data_dir
        self._assign_job_object(proc)

        # Edge/Chrome may run a launcher process that exits(0) after handing
        # off to the real browser — its exit is NOT failure. Wait for the
        # DevToolsActivePort file the real browser writes instead.
        deadline = time.monotonic() + 15.0
        port, _ws_path = 0, ""
        while time.monotonic() < deadline:
            try:
                port, _ws_path = parse_devtools_port_file(user_data_dir)
                break
            except (FileNotFoundError, ValueError):
                time.sleep(0.2)
        if not port:
            self._kill_profile_processes()
            self._proc = None
            raise BrowserTimeoutError("等待 DevToolsActivePort 超时（15s）")
        self._debug_port = port

        ws_url = self._page_ws_url(port)
        if not ws_url:
            self._kill_profile_processes()
            self._proc = None
            raise BrowserError("未在 /json/list 中找到 page 目标")
        try:
            from websockets.sync.client import connect

            self._ws = connect(ws_url, max_size=None, open_timeout=10)
        except Exception as exc:
            self._kill_profile_processes()
            self._proc = None
            raise BrowserError(f"CDP websocket 连接失败: {exc}") from exc

        self._alive = True
        self._pump = threading.Thread(target=self._pump_loop, name="nexuz-cdp-pump", daemon=True)
        self._pump.start()
        self.launched = True
        try:
            self._command("Page.enable", timeout=10)
        except BrowserError:
            self.close()
            raise

    def _assign_job_object(self, proc: subprocess.Popen) -> None:
        # Kill-on-close job: if Nexuz dies, the headless browser dies with it.
        try:
            job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
            info = ctypes.wintypes.JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ext = ctypes.wintypes.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ext.BasicLimitInformation = info
            ctypes.windll.kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(ext), ctypes.sizeof(ext)
            )
            ctypes.windll.kernel32.AssignProcessToJobObject(job, int(proc._handle))
        except Exception:
            pass  # best effort; close() still terminates explicitly

    def _page_ws_url(self, port: int) -> str:
        import urllib.request

        deadline = time.monotonic() + 10.0
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
                    targets = json.loads(resp.read().decode("utf-8"))
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            time.sleep(0.2)
        raise BrowserTimeoutError(f"等待 /json/list 超时: {last_exc}")

    def _pump_loop(self) -> None:
        while self._alive:
            sent = False
            try:
                item = self._send_q.get_nowait()
            except Empty:
                item = None
            if item is not None:
                sent = True
                try:
                    self._ws.send(json.dumps(item, ensure_ascii=False))
                except Exception:
                    self._mark_dead()
                    return
            try:
                raw = self._ws.recv(timeout=0.05 if sent else _WS_RECV_TIMEOUT)
            except TimeoutError:
                continue
            except Exception:
                self._mark_dead()
                return
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            mid = msg.get("id")
            if mid is not None:
                with self._pending_lock:
                    waiter = self._pending.pop(int(mid), None)
                if waiter is not None:
                    waiter["response"] = msg
                    waiter["event"].set()
            elif msg.get("method"):
                self._events.append(msg)

    def _mark_dead(self) -> None:
        self._alive = False
        with self._pending_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            waiter["error"] = BrowserSessionClosedError("浏览器连接已断开")
            waiter["event"].set()

    def _kill_profile_processes(self) -> None:
        """Terminate every browser process bound to our user-data-dir.

        The initially launched handle may be a short-lived launcher process,
        so process handles are not enough — match on the profile marker.
        """
        if self._user_data_dir is None:
            return
        marker = f"--user-data-dir={self._user_data_dir}"
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    if any(marker in str(c) for c in cmdline):
                        proc.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

    def is_alive(self) -> bool:
        # Launcher process may have exited while the real browser lives;
        # the ws pump is the source of truth.
        return bool(self._alive)

    def close(self) -> None:
        self._alive = False
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._kill_profile_processes()
        self._mark_dead()

    # ── command plumbing ──────────────────────────────────────────────

    def _command(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        if not self.is_alive():
            raise BrowserSessionClosedError("浏览器会话未启动或已关闭")
        mid = next(self._ids)
        waiter: dict[str, Any] = {"event": threading.Event(), "response": None, "error": None}
        with self._pending_lock:
            self._pending[mid] = waiter
        self._send_q.put({"id": mid, "method": method, "params": params or {}})
        if not waiter["event"].wait(timeout):
            with self._pending_lock:
                self._pending.pop(mid, None)
            raise BrowserTimeoutError(f"CDP 命令超时: {method}（{timeout:g}s）")
        if waiter["error"] is not None:
            raise waiter["error"]
        resp = waiter["response"] or {}
        if resp.get("error"):
            raise BrowserError(f"CDP {method} 失败: {resp['error'].get('message')}")
        return resp.get("result") or {}

    def _drain_new_events(self, after_len: int) -> list[dict[str, Any]]:
        evs = list(self._events)
        return evs[after_len:] if len(evs) > after_len else []

    # ── evaluate ──────────────────────────────────────────────────────

    def eval_js(self, expression: str, timeout_ms: int = 15000) -> Any:
        expr = str(expression or "").strip()
        if not expr:
            raise ValueError("expression 不能为空")
        timeout_s = max(0.1, timeout_ms / 1000.0)
        wrapped = (
            f"Promise.race(["
            f"(async () => ({expr}))(),"
            f"new Promise(r => setTimeout(() => r({{'__nexuz_timeout': true}}), {int(timeout_ms)}))"
            f"])"
        )
        result = self._command(
            "Runtime.evaluate",
            {
                "expression": wrapped,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
            timeout=timeout_s + 5.0,
        )
        details = result.get("exceptionDetails")
        if details:
            desc = (details.get("exception") or {}).get("description") or details.get("text") or "未知错误"
            raise BrowserEvalError(f"页面脚本执行失败: {desc}")
        value = (result.get("result") or {}).get("value")
        if isinstance(value, dict) and value.get("__nexuz_timeout"):
            raise BrowserTimeoutError(f"页面脚本超时（{timeout_ms}ms）")
        return value

    # ── navigation ────────────────────────────────────────────────────

    def navigate(self, url: str, timeout_ms: int = 30000) -> dict[str, Any]:
        url = str(url or "").strip()
        if not url:
            raise ValueError("url 不能为空")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            url = "https://" + url
        mark = len(self._events)
        self._command("Page.navigate", {"url": url}, timeout=max(5.0, timeout_ms / 1000.0))
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            for ev in self._drain_new_events(mark):
                if ev.get("method") == "Page.loadEventFired":
                    return {"url": self.current_url(), "title": self.title()}
            ready = self.eval_js("document.readyState", timeout_ms=2000)
            if ready == "complete":
                return {"url": self.current_url(), "title": self.title()}
            time.sleep(0.1)
        raise BrowserTimeoutError(f"页面加载超时（{timeout_ms}ms）: {url}")

    def current_url(self) -> str:
        return str(self.eval_js("location.href", timeout_ms=5000) or "")

    def title(self) -> str:
        return str(self.eval_js("document.title", timeout_ms=5000) or "")

    # ── viewport ──────────────────────────────────────────────────────

    def set_viewport(self, width: int, height: int) -> dict[str, Any]:
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError("视口尺寸必须是正数（像素）")
        # Layout viewport override: deterministic CSS pixel surface regardless
        # of the OS window frame. In headful mode Chromium may letterbox the
        # render surface instead of resizing the window — headless (default) is
        # the supported audit path.
        self._command(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
            timeout=10.0,
        )
        return {"width": width, "height": height}

    def viewport_size(self) -> dict[str, int]:
        metrics = self._command("Page.getLayoutMetrics", timeout=10.0)
        css = metrics.get("cssLayoutViewport") or metrics.get("layoutViewport") or {}
        return {
            "width": int(css.get("clientWidth") or 0),
            "height": int(css.get("clientHeight") or 0),
        }

    def quick_status(self) -> dict[str, Any]:
        # /json/list over HTTP: no ws roundtrip, safe for get_status polling.
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self._debug_port}/json/list", timeout=1.5
            ) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {}
        pages = [t for t in targets if t.get("type") == "page"]
        first = pages[0] if pages else {}
        return {
            "tabs": len(pages),
            "url": str(first.get("url") or ""),
            "title": str(first.get("title") or ""),
        }

    def list_tabs(self) -> list[dict[str, str]]:
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self._debug_port}/json/list", timeout=3.0
            ) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise BrowserError(f"获取页签列表失败: {exc}") from exc
        return [
            {"title": str(t.get("title") or ""), "url": str(t.get("url") or "")}
            for t in targets
            if t.get("type") == "page"
        ]

    # ── interaction ───────────────────────────────────────────────────

    def extract(self, selector: str, attr: str = "", max_items: int = 200) -> list[dict[str, Any]]:
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        js = _EXTRACT_JS.format(sel=_js_str(selector), attr=_js_str(attr or ""), max=max(1, int(max_items)))
        data = self.eval_js(js, timeout_ms=15000)
        if not isinstance(data, dict):
            return []
        return [element_record(el, attr) for el in data.get("items", []) if isinstance(el, dict)]

    def click(self, selector: str, timeout_ms: int = 10000, use_js: bool = False) -> dict[str, Any]:
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        js = (_JS_CLICK_JS if use_js else _CLICK_CENTER_JS).format(sel=_js_str(selector))
        pos = self.eval_js(js, timeout_ms=max(5.0, timeout_ms / 1000.0))
        if not isinstance(pos, dict) or not pos.get("found"):
            raise BrowserError(f"未找到元素: {selector}")
        if use_js:
            rect = pos.get("rect") or {}
            return {"x": float(rect.get("x") or 0), "y": float(rect.get("y") or 0)}
        x, y = float(pos.get("x") or 0), float(pos.get("y") or 0)
        for step in (
            {"type": "mouseMoved", "x": x, "y": y, "button": "none"},
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        ):
            self._command("Input.dispatchMouseEvent", step, timeout=10)
        return {"x": x, "y": y}

    def fill(self, selector: str, text: str, timeout_ms: int = 10000) -> dict[str, Any]:
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        js = _FILL_JS.format(sel=_js_str(selector), text=_js_str(text))
        res = self.eval_js(js, timeout_ms=max(5.0, timeout_ms / 1000.0))
        if not isinstance(res, dict) or not res.get("found"):
            raise BrowserError(f"未找到元素: {selector}")
        return {"ok": True}

    # ── capture / wait ────────────────────────────────────────────────

    def screenshot(
        self,
        save_path: str | None = None,
        full_page: bool = True,
        clip: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"format": "png", "captureBeyondViewport": bool(full_page)}
        if clip is not None:
            try:
                box = {
                    "x": float(clip["x"]),
                    "y": float(clip["y"]),
                    "width": float(clip["width"]),
                    "height": float(clip["height"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"clip 参数无效: {clip}") from exc
            if box["width"] <= 0 or box["height"] <= 0:
                raise ValueError(f"clip 尺寸必须为正: {box}")
            box["scale"] = 1
            params["clip"] = box
        result = self._command("Page.captureScreenshot", params, timeout=30.0)
        raw = base64.b64decode(result.get("data") or "")
        png = bytearray(raw)
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        path = Path(save_path) if save_path else None
        if path is None:
            raise ValueError("save_path 不能为空（积木层负责生成默认路径）")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() not in (".png",):
            path = path.with_suffix(".png")
        path.write_bytes(raw)
        try:
            viewport = self.viewport_size()
        except BrowserError:
            viewport = {"width": 0, "height": 0}
        return {
            "path": str(path.resolve()),
            "width": width,
            "height": height,
            "viewport_width": viewport["width"],
            "viewport_height": viewport["height"],
        }

    def wait_document(self, state: str, timeout_ms: int = 30000) -> dict[str, Any]:
        target = "interactive" if state == "interactive" else "complete"
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            try:
                if str(self.eval_js("document.readyState", timeout_ms=2000)) == target:
                    return {"ready_state": target, "url": self.current_url()}
            except BrowserError:
                pass
            time.sleep(0.15)
        raise BrowserTimeoutError(f"等待 readyState={target} 超时（{timeout_ms}ms）")
