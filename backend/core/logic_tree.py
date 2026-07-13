"""Nested boolean logic tree for if_logic (AND / OR / NOT / groups)."""

from __future__ import annotations

from typing import Any

from .expression import evaluate_expression


def empty_logic_tree() -> dict[str, Any]:
    return {
        "kind": "group",
        "id": "root",
        "op": "and",
        "not": False,
        "children": [
            {
                "kind": "expr",
                "id": "c0",
                "expression": "",
                "not": False,
                "label": "",
            }
        ],
    }


def normalize_logic_tree(params: dict[str, Any] | None) -> dict[str, Any]:
    """Accept new ``logic`` tree or legacy ``mode`` + ``conditions`` list."""
    params = params or {}
    logic = params.get("logic")
    if isinstance(logic, dict) and (logic.get("kind") or logic.get("type")):
        return _normalize_node(logic, fallback_id="root")

    mode = str(params.get("mode") or "and").lower()
    if mode not in ("and", "or"):
        mode = "and"
    raw = params.get("conditions")
    children: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if isinstance(item, str):
                expr = item
            elif isinstance(item, dict):
                expr = str(item.get("expression") or "")
            else:
                expr = ""
            children.append(
                {
                    "kind": "expr",
                    "id": f"legacy_{i}",
                    "expression": expr,
                    "not": False,
                    "label": "",
                }
            )
    if not children:
        return empty_logic_tree()
    return {
        "kind": "group",
        "id": "root",
        "op": mode,
        "not": False,
        "children": children,
    }


def _normalize_node(node: dict[str, Any], fallback_id: str = "n") -> dict[str, Any]:
    kind = str(node.get("kind") or node.get("type") or "expr").lower()
    nid = str(node.get("id") or fallback_id)
    negated = bool(node.get("not"))
    if kind in ("expr", "leaf", "condition"):
        return {
            "kind": "expr",
            "id": nid,
            "expression": str(node.get("expression") or ""),
            "not": negated,
            "label": str(node.get("label") or ""),
        }
    # group
    op = str(node.get("op") or "and").lower()
    if op not in ("and", "or"):
        op = "and"
    raw_children = node.get("children")
    children: list[dict[str, Any]] = []
    if isinstance(raw_children, list):
        for i, child in enumerate(raw_children):
            if isinstance(child, dict):
                children.append(_normalize_node(child, fallback_id=f"{nid}_{i}"))
            elif isinstance(child, str):
                children.append(
                    {
                        "kind": "expr",
                        "id": f"{nid}_{i}",
                        "expression": child,
                        "not": False,
                        "label": "",
                    }
                )
    if not children:
        children = [
            {
                "kind": "expr",
                "id": f"{nid}_0",
                "expression": "",
                "not": False,
                "label": "",
            }
        ]
    return {
        "kind": "group",
        "id": nid,
        "op": op,
        "not": negated,
        "children": children,
    }


def evaluate_logic_tree(node: dict[str, Any], context: dict[str, Any]) -> tuple[bool, int, int]:
    """
    Evaluate nested logic tree.
    Returns (matched, matched_leaf_count, total_leaf_count).
    """
    tree = _normalize_node(node if isinstance(node, dict) else empty_logic_tree())
    matched, leaf_hits, leaf_total = _eval(tree, context)
    return matched, leaf_hits, leaf_total


def _eval(node: dict[str, Any], context: dict[str, Any]) -> tuple[bool, int, int]:
    kind = node.get("kind")
    if kind == "expr":
        expr = str(node.get("expression") or "").strip()
        if not expr:
            raise ValueError(f"条件「{node.get('label') or node.get('id') or '?'}」表达式为空")
        ok = bool(evaluate_expression(expr, context))
        if node.get("not"):
            ok = not ok
        return ok, (1 if ok else 0), 1

    children = node.get("children") or []
    if not children:
        raise ValueError("条件组不能为空")
    op = str(node.get("op") or "and").lower()
    results: list[bool] = []
    hits = 0
    total = 0
    for child in children:
        ok, h, t = _eval(child, context)
        results.append(ok)
        hits += h
        total += t
    combined = any(results) if op == "or" else all(results)
    if node.get("not"):
        combined = not combined
    return combined, hits, total
