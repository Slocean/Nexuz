"""Offline AI eval runner (heuristic / FlowSpec apply, no live LLM required)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.ai.draft_builder import empty_draft, params_need_coord_refs
from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text
from backend.core.ai.lc.structured import flow_spec_to_dict
from backend.core.registry import register_all_blocks

_CASES_PATH = Path(__file__).resolve().parents[2] / "testdata" / "ai_eval" / "cases.json"


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or _CASES_PATH
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
    utterance = str(case.get("utterance") or "")
    plan = heuristic_plan_from_text(utterance)
    draft = empty_draft()
    applied = apply_flow_spec(draft, plan, strict_coords=True)
    draft = applied["draft"]
    types = _node_types(draft)
    expected = list(case.get("expected_types") or [])
    optional = set(case.get("optional_types") or [])
    required = [t for t in expected if t not in optional]

    # Soft: optional types may be absent; still require core action types present
    if optional:
        core = [
            t
            for t in required
            if t
            in (
                "delay",
                "type_text",
                "key_press",
                "ocr_recognize",
                "click",
                "wait_until",
                "schedule_trigger",
                "window_activate",
                "find_image",
                "color_detect",
                "if_text_contains",
                "loop_n",
                "try_catch",
            )
        ]
        if not core:
            core = [t for t in expected if t not in optional][:2]
        missing = [t for t in core if t not in types]
    else:
        # Multiset soft match: each expected type must appear at least once
        missing = []
        for t in required:
            if t not in types:
                missing.append(t)

    errors: list[str] = []
    if missing:
        errors.append(f"missing types {missing}; got {types}")
    if case.get("expect_connected") and not _is_connected(draft):
        errors.append("nodes not connected from entry")
    if case.get("forbid_raw_click_coords") and _has_raw_click_coords(draft):
        errors.append("raw click coordinates present")
    if case.get("expect_binding_on_click") and not _click_has_binding(draft):
        errors.append("click missing {{binding}}")
    if case.get("expect_clarify"):
        plan_dict = flow_spec_to_dict(plan)
        qs = plan_dict.get("clarify_questions") or []
        if not qs:
            errors.append("expected clarify_questions")
    if case.get("must_validate"):
        if not draft.get("entry") and types:
            errors.append("missing entry")
        if applied.get("errors"):
            errors.append(f"apply errors: {applied['errors']}")

    return {
        "id": case.get("id"),
        "ok": not errors,
        "errors": errors,
        "types": types,
        "utterance": utterance,
    }


def run_eval_suite(path: Path | None = None) -> dict[str, Any]:
    register_all_blocks()
    cases = load_eval_cases(path)
    results = [evaluate_case(c) for c in cases]
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    rate = (passed / total) if total else 0.0
    # Done gate: ≥60 cases & ≥85%; Plan1 CI kept ≥90% when smaller suites
    min_rate = 0.85 if total >= 60 else 0.9
    return {
        "ok": total > 0 and rate >= min_rate,
        "passed": passed,
        "total": total,
        "pass_rate": rate,
        "min_rate": min_rate,
        "results": results,
    }
