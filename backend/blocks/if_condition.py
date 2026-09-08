from __future__ import annotations

from backend.core.expression import evaluate_expression

SCHEMA = {
    "type": "if_condition",
    "description": "按数值/字符串比较条件成立与否走 then/else 分支。",
    "label": "条件分支",
    "category": "控制类",
    "inputs": [
        {
            "name": "expression",
            "type": "string",
            "label": "表达式",
            "default": "",
            "bindable": False,
            "ui": "expression",
        }
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
    ],
}


def handler(params, context, **kwargs):
    expr = params.get("expression", "")
    matched = evaluate_expression(str(expr), context)
    return {"matched": matched}
