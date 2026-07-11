from __future__ import annotations

from backend.core.expression import evaluate_expression

SCHEMA = {
    "type": "if_condition",
    "label": "条件分支",
    "category": "控制类",
    "inputs": [
        {
            "name": "expression",
            "type": "string",
            "label": "表达式",
            "default": "",
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
