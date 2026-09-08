from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_tabs",
    "label": "浏览器页签列表",
    "category": "浏览器",
    "description": "列出当前浏览器的页签（title/url）。只读；当前引擎架构只操作第一个页签，不支持切换。",
    "inputs": [],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "tabs", "type": "array", "itemType": "object", "canvas": False},
        {"name": "count", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    def op(eng):
        tabs = eng.list_tabs()
        return {"tabs": tabs, "count": len(tabs)}

    return call_engine(op)
