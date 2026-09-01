"""DrissionPage backend (optional dependency, engine="drission").

Maps the BrowserEngine interface onto ChromiumPage. DrissionPage is NOT a
hard dependency — import lazily and raise with install guidance when absent.
API names target DrissionPage 4.x; verify against the installed version when
this backend is exercised (see plan verification section).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.browser.engine import BrowserEngine, element_record
from backend.core.browser.errors import BrowserError, BrowserEvalError

_INSTALL_HINT = "未安装 DrissionPage：执行 pip install DrissionPage 后重启 Nexuz，或在设置中切换引擎为 cdp"


def _import():
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage  # noqa: F401

        return ChromiumOptions, ChromiumPage
    except Exception as exc:  # pragma: no cover - exercised only without the package
        raise BrowserError(_INSTALL_HINT) from exc


class DrissionEngine(BrowserEngine):
    def __init__(self) -> None:
        self._page: Any = None
        self._headless = True

    def launch(self, *, headless: bool, user_data_dir: Path, binary_path: str = "") -> None:
        if self.is_alive():
            return
        ChromiumOptions, ChromiumPage = _import()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        co = ChromiumOptions()
        self._headless = bool(headless)
        if headless:
            co.headless(True)
        co.set_user_data_path(str(user_data_dir))
        if binary_path:
            co.set_browser_path(binary_path)
        try:
            self._page = ChromiumPage(co)
        except Exception as exc:
            self._page = None
            raise BrowserError(f"DrissionPage 启动浏览器失败: {exc}") from exc

    def close(self) -> None:
        page, self._page = self._page, None
        if page is None:
            return
        try:
            page.quit(force=True)
        except Exception:
            try:
                page.quit()
            except Exception:
                pass

    def is_alive(self) -> bool:
        if self._page is None:
            return False
        try:
            _ = self._page.url
            return True
        except Exception:
            return False

    def _require(self) -> Any:
        if self._page is None:
            raise BrowserError("浏览器会话未启动")
        return self._page

    def navigate(self, url: str, timeout_ms: int = 30000) -> dict[str, Any]:
        page = self._require()
        target = str(url or "").strip()
        if not target:
            raise ValueError("url 不能为空")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            target = "https://" + target
        try:
            page.get(target, timeout=max(1, int(timeout_ms / 1000)))
        except Exception as exc:
            raise BrowserError(f"导航失败: {exc}") from exc
        return {"url": self.current_url(), "title": self.title()}

    def current_url(self) -> str:
        return str(self._require().url or "")

    def title(self) -> str:
        return str(self._require().title or "")

    def eval_js(self, expression: str, timeout_ms: int = 15000) -> Any:
        page = self._require()
        expr = str(expression or "").strip()
        if not expr:
            raise ValueError("expression 不能为空")
        try:
            return page.run_js(f"return ({expr})")
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserEvalError(f"页面脚本执行失败: {exc}") from exc

    def extract(self, selector: str, attr: str = "", max_items: int = 200) -> list[dict[str, Any]]:
        page = self._require()
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        try:
            eles = page.eles(str(selector), timeout=5)
        except Exception as exc:
            raise BrowserError(f"提取失败: {exc}") from exc
        out: list[dict[str, Any]] = []
        for el in list(eles or [])[: max(1, int(max_items))]:
            rect = el.rect.location
            out.append(
                element_record(
                    {
                        "text": el.text,
                        "value": el.attr("value"),
                        "href": el.attr("href"),
                        "attr": el.attr(attr) if attr else None,
                        "rect": {"x": rect[0], "y": rect[1], "width": el.rect.size[0], "height": el.rect.size[1]},
                    },
                    attr,
                )
            )
        return out

    def click(self, selector: str, timeout_ms: int = 10000, use_js: bool = False) -> dict[str, Any]:
        page = self._require()
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        el = page.ele(str(selector), timeout=max(0.5, timeout_ms / 1000))
        if el is None:
            raise BrowserError(f"未找到元素: {selector}")
        try:
            el.click(by_js=True if use_js else None)
        except TypeError:
            el.click()
        rect = el.rect.location
        return {"x": float(rect[0]), "y": float(rect[1])}

    def fill(self, selector: str, text: str, timeout_ms: int = 10000) -> dict[str, Any]:
        page = self._require()
        if not str(selector or "").strip():
            raise ValueError("selector 不能为空")
        el = page.ele(str(selector), timeout=max(0.5, timeout_ms / 1000))
        if el is None:
            raise BrowserError(f"未找到元素: {selector}")
        try:
            el.clear()
            el.input(str(text))
        except Exception as exc:
            raise BrowserError(f"填充失败: {exc}") from exc
        return {"ok": True}

    def screenshot(self, save_path: str | None = None, full_page: bool = True) -> dict[str, Any]:
        page = self._require()
        if not save_path:
            raise ValueError("save_path 不能为空（积木层负责生成默认路径）")
        path = Path(save_path).with_suffix(".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.get_screenshot(path=str(path), full_page=bool(full_page))
        except TypeError:
            page.get_screenshot(str(path))
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
        return {"path": str(path.resolve()), "width": width, "height": height}

    def wait_document(self, state: str, timeout_ms: int = 30000) -> dict[str, Any]:
        target = "interactive" if state == "interactive" else "complete"
        page = self._require()
        page.wait.doc_loaded(timeout=max(0.5, timeout_ms / 1000))
        return {"ready_state": target, "url": self.current_url()}
