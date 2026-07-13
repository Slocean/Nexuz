from __future__ import annotations

from backend.core.logic_tree import empty_logic_tree, evaluate_logic_tree, normalize_logic_tree

SCHEMA = {
    "type": "if_logic",
    "label": "组合条件",
    "category": "控制类",
    "inputs": [
        {
            "name": "logic",
            "type": "logic_tree",
            "label": "条件树",
            "default": empty_logic_tree(),
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
    """
    Nested boolean composition:
      (A AND B) OR (C AND D)  →  group(or, [group(and,[A,B]), group(and,[C,D])])
    Supports NOT on leaves and groups. Legacy mode+conditions still accepted.
    """
    tree = normalize_logic_tree(params or {})
    matched, matched_count, total = evaluate_logic_tree(tree, context)
    return {
        "matched": matched,
        "matched_count": matched_count,
        "total": total,
    }
