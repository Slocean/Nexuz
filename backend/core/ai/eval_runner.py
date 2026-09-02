"""Offline AI eval runner (PlanIR compile only — no keyword task routing).

两层用例：
- cases.json（compile 层）：已归一 PlanIR → compile_ir → 节点类型/连通性断言。
- raw_cases.json（原始层）：录制自真实网关的"脏"LLM 输出（别名 op、裸字符串
  参数、未知 op、重复步）→ PlanIRDraft 宽松解析 + normalize_plan_ir →
  归一化后精确断言。用例可带 "models": [...] 标注录制来源，支持按模型分组跑分。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.ai.draft_builder import empty_draft, params_need_coord_refs
from backend.core.ai.graphs.agent_ir import (
    PlanIR,
    PlanIRDraft,
    IrStep,
    merge_and_normalize,
    normalize_plan_ir,
)
from backend.core.ai.graphs.ir_compile import compile_ir
from backend.core.registry import register_all_blocks

_CASES_PATH = Path(__file__).resolve().parents[2] / "testdata" / "ai_eval" / "cases.json"
_RAW_CASES_PATH = Path(__file__).resolve().parents[2] / "testdata" / "ai_eval" / "raw_cases.json"


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


# ---------------------------------------------------------------------------
# 原始层：脏 LLM 输出（录制响应）→ 归一化 → 精确断言
# ---------------------------------------------------------------------------


def load_raw_cases(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or _RAW_CASES_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("raw eval cases must be a JSON array")
    return [c for c in data if isinstance(c, dict)]


def _raw_case_applies_to_model(case: dict[str, Any], model: str | None) -> bool:
    """用例未标注 models 时对所有模型生效；标注了则只在分组跑分时纳入。"""
    models = case.get("models")
    if not isinstance(models, list) or not models:
        return True
    if model is None:
        return True  # 全量跑分时包含所有录制来源
    return str(model).strip().lower() in {str(m).strip().lower() for m in models}


def evaluate_raw_case(case: dict[str, Any]) -> dict[str, Any]:
    """脏 LLM 输出 → PlanIRDraft（别名/裸参数/arg 名归一）→ normalize → 断言。

    断言语义与 compile 层不同：expected_ops 要求**精确相等**（录制回归的
    本意是锁定归一化行为），另支持 forbid_ops 与 expected_args 键值断言。
    """
    utterance = str(case.get("utterance") or "")
    slots = merge_and_normalize(case.get("slots") or {}, utterance="")
    raw_steps = case.get("raw_steps") or []
    errors: list[str] = []

    try:
        loose = PlanIRDraft.model_validate({"steps": raw_steps})
        # 与生产一致：宽松解析产物以 dict 形态进入归一化（别名 op 无法通过
        # 严格 PlanIR 的 Literal 校验，normalize_plan_ir 负责收敛）
        plan = normalize_plan_ir(loose.model_dump(), slots)
    except Exception as exc:
        return {
            "id": case.get("id"),
            "ok": False,
            "errors": [f"parse failed: {exc}"],
            "ir_ops": [],
            "utterance": utterance,
        }
    ir_ops = [st.op for st in plan.steps]

    expected = case.get("expected_ops")
    if expected is not None and [str(x) for x in expected] != ir_ops:
        errors.append(f"ops mismatch: expected {list(expected)}; got {ir_ops}")
    for op in case.get("forbid_ops") or []:
        if op in ir_ops:
            errors.append(f"forbidden op present: {op}")

    # 参数键值断言：{"op": "key", "key": "keys", "value": "Enter"} →
    # 第一个该 op 步骤的 a[key] 必须等于 value
    by_op: dict[str, dict[str, str]] = {}
    for st in plan.steps:
        by_op.setdefault(st.op, dict(st.a or {}))
    for cond in case.get("expected_args") or []:
        if not isinstance(cond, dict):
            continue
        op = str(cond.get("op") or "")
        key = str(cond.get("key") or "")
        want = str(cond.get("value") or "")
        got = by_op.get(op, {}).get(key)
        if got != want:
            errors.append(f"args[{op}.{key}] expected {want!r}; got {got!r}")

    return {
        "id": case.get("id"),
        "ok": not errors,
        "errors": errors,
        "ir_ops": ir_ops,
        "utterance": utterance,
    }


def run_raw_eval_suite(
    path: Path | None = None, *, model: str | None = None
) -> dict[str, Any]:
    """原始层跑分。model 指定时只跑该模型分组的录制用例，并输出分组对比。"""
    register_all_blocks()
    cases = [c for c in load_raw_cases(path) if _raw_case_applies_to_model(c, model)]
    results = [evaluate_raw_case(c) for c in cases]
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    rate = (passed / total) if total else 0.0
    min_rate = 0.85 if total >= 60 else 0.9

    by_model: dict[str, dict[str, Any]] = {}
    for case, res in zip(cases, results):
        tags = [str(m) for m in (case.get("models") or [])] or ["<shared>"]
        for tag in tags:
            bucket = by_model.setdefault(tag, {"passed": 0, "total": 0})
            bucket["total"] += 1
            if res["ok"]:
                bucket["passed"] += 1

    return {
        "ok": total > 0 and rate >= min_rate,
        "model": model,
        "passed": passed,
        "total": total,
        "pass_rate": rate,
        "min_rate": min_rate,
        "by_model": by_model,
        "results": results,
    }
