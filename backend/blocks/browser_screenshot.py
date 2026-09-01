from __future__ import annotations

from backend.blocks._browser import call_engine, default_screenshot_path

SCHEMA = {
    "type": "browser_screenshot",
    "label": "浏览器截图",
    "category": "浏览器",
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
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "path", "type": "string"},
        {"name": "width", "type": "number"},
        {"name": "height", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    save_path = str(params.get("save_path") or "").strip()
    full_page = params.get("full_page")
    full_page = True if full_page is None else bool(full_page)

    def op(eng):
        path = save_path or str(default_screenshot_path())
        return eng.screenshot(save_path=path, full_page=full_page)

    return call_engine(op)
