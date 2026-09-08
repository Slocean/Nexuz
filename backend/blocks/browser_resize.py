from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_resize",
    "label": "浏览器视口",
    "category": "浏览器",
    "description": "调整浏览器布局视口为指定宽×高（像素）。截图、样式审计前先定视口，避免默认窗口尺寸导致布局失真。",
    "inputs": [
        {
            "name": "width",
            "type": "number",
            "label": "视口宽度(px)",
            "default": 1280,
        },
        {
            "name": "height",
            "type": "number",
            "label": "视口高度(px)",
            "default": 800,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    try:
        width = int(float(params.get("width") or 0))
        height = int(float(params.get("height") or 0))
    except (TypeError, ValueError):
        width = height = 0

    def op(eng):
        applied = eng.set_viewport(width, height)
        return {"width": applied.get("width", width), "height": applied.get("height", height)}

    return call_engine(op)
