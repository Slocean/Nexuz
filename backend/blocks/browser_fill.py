from __future__ import annotations

from backend.blocks._browser import call_engine

SCHEMA = {
    "type": "browser_fill",
    "description": "向浏览器输入框填文本（触发 input/change 事件），支持 ref 定位。",
    "label": "浏览器填充",
    "category": "浏览器",
    "inputs": [
        {
            "name": "selector",
            "type": "string",
            "label": "CSS 选择器",
            "default": "",
            "placeholder": "例如 input[name='q']；留空可用 ref",
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
            "name": "text",
            "type": "string",
            "label": "填充内容",
            "default": "",
            "ui": "textarea",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    selector = str(params.get("selector") or "").strip()
    ref = str(params.get("ref") or "").strip()
    text = "" if params.get("text") is None else str(params.get("text"))

    def op(eng):
        from backend.blocks.browser_snapshot import resolve_ref

        target = selector or resolve_ref(eng, ref)
        return eng.fill(target, text)

    return call_engine(op)
