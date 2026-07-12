from __future__ import annotations

SCHEMA = {
    "type": "loop_while",
    "label": "条件循环",
    "category": "控制类",
    "inputs": [
        {"name": "expression", "type": "string", "label": "继续条件", "default": "", "bindable": False, "ui": "expression"},
        {"name": "max_times", "type": "number", "label": "最大次数", "default": 10000},
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
    ],
}


def handler(params, context, **kwargs):
    from backend.core.expression import evaluate_expression

    matched = evaluate_expression(str(params.get("expression", "")), context)
    return {"matched": matched}
