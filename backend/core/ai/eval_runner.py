"""Offline AI eval runner (PlanIR compile only — no keyword task routing)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.ai.draft_builder import empty_draft, params_need_coord_refs
from backend.core.ai.graphs.agent_ir import (
    PlanIR,
    IrStep,
    merge_and_normalize,
    normalize_plan_ir,
)
from backend.core.ai.graphs.ir_compile import compile_ir
from backend.core.registry import register_all_blocks

_CASES_PATH = Path(__file__).resolve().parents[2] / "testdata" / "ai_eval" / "cases.json"


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or _CASES_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("eval cases must be a JSON array")
    return [c for c in data if isinstance(c, dict)]


def _node_types(draft: dict[str, Any]) -> list[str]:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    order: list[str] = []
    seen: set[str] = set()
    cur = draft.get("entry")
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        node = nodes[cur]
        if isinstance(node, dict):
            order.append(str(node.get("type") or ""))
            cur = node.get("next")
        else:
            break
    for nid, node in nodes.items():
        if nid in seen or not isinstance(node, dict):
            continue
        order.append(str(node.get("type") or ""))
    return order


def _is_connected(draft: dict[str, Any]) -> bool:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if len(nodes) <= 1:
        return True
    entry = draft.get("entry")
    if not entry or entry not in nodes:
        return False
    seen: set[str] = set()
    cur = entry
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        nxt = nodes[cur].get("next") if isinstance(nodes[cur], dict) else None
        cur = nxt
    return len(seen) >= min(2, len(nodes))


def _click_has_binding(draft: dict[str, Any]) -> bool:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    clicks = [
        n
        for n in nodes.values()
        if isinstance(n, dict) and n.get("type") == "click"
    ]
    if not clicks:
        return True
    for node in clicks:
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        x, y = params.get("x"), params.get("y")
        if isinstance(x, str) and "{{" in x and isinstance(y, str) and "{{" in y:
            continue
        return False
    return True


def _has_raw_click_coords(draft: dict[str, Any]) -> bool:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    for node in nodes.values():
        if not isinstance(node, dict) or node.get("type") != "click":
            continue
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        if params_need_coord_refs(params):
            return True
    return False


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a case that supplies plan_ir / slots — never keyword-routes utterance."""
    utterance = str(case.get("utterance") or "")
    slots = merge_and_normalize(case.get("slots") or {}, utterance="")
    raw_steps = case.get("plan_ir") or case.get("steps") or []
    steps: list[IrStep] = []
    if isinstance(raw_steps, list):
        for raw in raw_steps:
            if not isinstance(raw, dict):
                continue
            op = str(raw.get("op") or "").strip()
            args = raw.get("a") if isinstance(raw.get("a"), dict) else {}
            if not args and isinstance(raw.get("args"), dict):
                args = raw["args"]
            if not op:
                continue
            try:
                steps.append(IrStep(op=op, a={str(k): str(v) for k, v in args.items()}))  # type: ignore[arg-type]
            except Exception:
                continue
    plan_ir = normalize_plan_ir(PlanIR(steps=steps), slots)
    ir_ops = [st.op for st in plan_ir.steps]
    applied = compile_ir(
        plan_ir, slots, empty_draft(), strict_coords=True, utterance=utterance
    )
    draft = applied["draft"]

    types = _node_types(draft)
    expected = list(case.get("expected_types") or [])
    optional = set(case.get("optional_types") or [])
    required = [t for t in expected if t not in optional]

    if optional:
        core = [t for t in required if t][:2]
        missing = [t for t in core if t not in types]
    else:
        missing = [t for t in required if t not in types]

    errors: list[str] = []
    clarify_only = bool(case.get("clarify_only"))
    if missing and not clarify_only:
        errors.append(f"missing types {missing}; got {types}")
    expected_ops = case.get("expected_ops")
    if expected_ops is not None:
        exp = [str(x) for x in expected_ops]
        for op in exp:
            if op not in ir_ops:
                errors.append(f"missing ir op {op}; got {ir_ops}")
    if case.get("expect_connected") and not _is_connected(draft) and not clarify_only:
        errors.append("nodes not connected from entry")
    if case.get("forbid_raw_click_coords") and _has_raw_click_coords(draft):
        errors.append("raw click coordinates present")
    if case.get("expect_binding_on_click") and not _click_has_binding(draft):
        errors.append("click missing {{binding}}")
    forbid_types = list(case.get("forbid_types") or [])
    for ft in forbid_types:
        if ft in types:
            errors.append(f"forbidden type present: {ft}")
    if case.get("must_validate") and not clarify_only:
        if not draft.get("entry") and types:
            errors.append("missing entry")
        if applied.get("errors"):
            errors.append(f"apply errors: {applied['errors']}")

    return {
        "id": case.get("id"),
        "ok": not errors,
        "errors": errors,
        "types": types,
        "ir_ops": ir_ops,
        "utterance": utterance,
    }


def run_eval_suite(path: Path | None = None) -> dict[str, Any]:
    register_all_blocks()
    cases = load_eval_cases(path)
    results = [evaluate_case(c) for c in cases]
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    rate = (passed / total) if total else 0.0
    min_rate = 0.85 if total >= 60 else 0.9
    return {
        "ok": total > 0 and rate >= min_rate,
        "passed": passed,
        "total": total,
        "pass_rate": rate,
        "min_rate": min_rate,
        "results": results,
    }
