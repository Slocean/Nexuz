from __future__ import annotations

from backend.core.expression import evaluate_expression

SCHEMA = {
    "type": "if_logic",
    "label": "组合条件",
    "category": "控制类",
    "inputs": [
        {
            "name": "mode",
            "type": "select",
            "label": "组合方式",
            "options": ["and", "or"],
            "default": "and",
            "option_labels": {
                "and": "全部满足（与 AND）",
                "or": "任一满足（或 OR）",
            },
        },
        {
            "name": "conditions",
            "type": "condition_list",
            "label": "条件列表",
            "default": [{"expression": ""}],
            "bindable": False,
        },
    ],
    "outputs": [
        {"name": "matched", "type": "boolean"},
        {"name": "matched_count", "type": "number"},
        {"name": "total", "type": "number"},
    ],
}


def handler(params, context, **kwargs):
    mode = str(params.get("mode") or "and").lower()
    raw = params.get("conditions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("组合条件需要至少一条条件")

    results: list[bool] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            expr = item
        elif isinstance(item, dict):
            expr = str(item.get("expression") or "")
        else:
            expr = ""
        if not str(expr).strip():
            raise ValueError(f"第 {i + 1} 条条件表达式为空")
        results.append(bool(evaluate_expression(str(expr), context)))

    matched_count = sum(1 for r in results if r)
    total = len(results)
    if mode == "or":
        matched = matched_count > 0
    else:
        matched = matched_count == total and total > 0

    return {
        "matched": matched,
        "matched_count": matched_count,
        "total": total,
    }
