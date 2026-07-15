from __future__ import annotations

SCHEMA = {
    "type": "switch",
    "label": "多分支",
    "category": "控制类",
    "inputs": [
        {
            "name": "variable",
            "type": "string",
            "label": "判断值",
            "default": "",
        },
        {
            "name": "cases",
            "type": "cases",
            "label": "分支",
            "default": [],
            "description": "每条分支可设比较方式（等于/包含/大于等），自上而下首次命中即跳转",
        },
        {
            "name": "default",
            "type": "string",
            "label": "默认分支",
            "default": "",
            "bindable": False,
            "placeholder": "未匹配时跳转",
        },
    ],
    "outputs": [
        {"name": "value", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from backend.core.variable_resolver import resolve_value

    variable = params.get("variable", "")
    value = resolve_value(variable, context) if variable else None
    return {"value": value}
