from __future__ import annotations

from backend.blocks._browser import call_engine, default_screenshot_path

# 返回元素矩形（文档坐标 + 视口坐标），供 clip_selector 换算裁剪区
_ELEMENT_RECT_JS = """
(() => {
  const el = document.querySelector("SEL");
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {
    doc: {x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height},
    vp: {x: r.x, y: r.y, width: r.width, height: r.height},
  };
})()
"""

SCHEMA = {
    "type": "browser_screenshot",
    "label": "浏览器截图",
    "category": "浏览器",
    "description": "截取浏览器页面：整页或视口，支持按区域（clip）或按元素（clip_selector）裁剪；回传视口尺寸供核对。",
    "inputs": [
        {
            "name": "save_path",
            "type": "string",
            "label": "保存路径",
            "default": "",
            "placeholder": "留空则自动保存",
        },
        {
            "name": "full_page",
            "type": "boolean",
            "label": "整页截图",
            "default": True,
        },
        {
            "name": "clip",
            "type": "rect",
            "label": "裁剪区域 [x1,y1,x2,y2]",
            "default": None,
            "placeholder": "整页=文档坐标，视口=视口坐标；留空=不裁剪",
        },
        {
            "name": "clip_selector",
            "type": "string",
            "label": "按元素裁剪（CSS 选择器）",
            "default": "",
            "placeholder": "例如 #card；与 clip 二选一，元素优先",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "path", "type": "string"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "viewport_width", "type": "number"},
        {"name": "viewport_height", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def _parse_clip(value) -> dict[str, float] | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"无效 clip: {value}（需要 [x1,y1,x2,y2]）")
    try:
        x1, y1, x2, y2 = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效 clip: {list(value)}") from exc
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效裁剪区域: {list(value)}")
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def handler(params, context, **kwargs):
    save_path = str(params.get("save_path") or "").strip()
    full_page = params.get("full_page")
    full_page = True if full_page is None else bool(full_page)
    clip = _parse_clip(params.get("clip"))
    clip_selector = str(params.get("clip_selector") or "").strip()
    if clip is not None and clip_selector:
        raise ValueError("clip 与 clip_selector 二选一")

    def op(eng):
        nonlocal clip
        if clip_selector:
            clip = _element_clip(eng, clip_selector, full_page=full_page)
        path = save_path or str(default_screenshot_path())
        return eng.screenshot(save_path=path, full_page=full_page, clip=clip)

    return call_engine(op)


def _element_clip(eng, selector: str, *, full_page: bool) -> dict[str, float]:
    from backend.core.browser.errors import BrowserError

    js = _ELEMENT_RECT_JS.replace("SEL", selector.replace("\\", "\\\\").replace('"', '\\"'))
    rect = eng.eval_js(js, timeout_ms=10000)
    if not isinstance(rect, dict):
        raise BrowserError(f"未找到元素: {selector}")
    box = rect.get("doc" if full_page else "vp") or {}
    try:
        clip = {
            "x": float(box["x"]),
            "y": float(box["y"]),
            "width": float(box["width"]),
            "height": float(box["height"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BrowserError(f"元素矩形不可用: {selector}") from exc
    if clip["width"] <= 0 or clip["height"] <= 0:
        raise BrowserError(f"元素不可见（尺寸为 0）: {selector}")
    return clip
