from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_click",
    "description": "点击浏览器页面元素：CSS 选择器或快照 ref，默认真实鼠标事件。",
    "label": "浏览器点击",
    "category": "浏览器",
    "inputs": [
        {
            "name": "selector",
            "type": "string",
            "label": "CSS 选择器",
            "default": "",
            "placeholder": "例如 #submit-btn；留空可用 ref",
            "bindable": True,
        },
        {
            "name": "ref",
            "type": "string",
            "label": "快照 ref",
            "default": "",
            "placeholder": "browser_snapshot 的 e1..eN；selector 为空时生效",
            "bindable": True,
        },
        {
            "name": "use_js",
            "type": "boolean",
            "label": "用页面 JS 点击",
            "default": False,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "x", "type": "number"},
        {"name": "y", "type": "number"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    selector = str(params.get("selector") or "").strip()
    ref = str(params.get("ref") or "").strip()
    use_js = bool(params.get("use_js"))

    def op(eng):
        from backend.blocks.browser_snapshot import resolve_ref

        target = selector or resolve_ref(eng, ref)
        pos = eng.click(target, use_js=use_js)
        return {"x": pos.get("x", 0), "y": pos.get("y", 0)}

    return call_engine(op)
