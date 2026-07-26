"""Compact Agent IR: slim LLM-facing schemas + normalization + slot→plan helpers.

LLM outputs decision bits only; ir_compile expands into real draft nodes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.ai.graphs.slot_extract import extract_slots_from_utterance, merge_slots

# Canonical slot keys the interpreter accepts.
CANONICAL_SLOT_KEYS = (
    "window_title",
    "contact",
    "message",
    "run_at",
    "schedule",
    "match_text",
    "ms",
    "key",
    "image_ref",
    "color",
    "n",
)

# LLM / alias → canonical
_SLOT_ALIASES: dict[str, str] = {
    "platform": "window_title",
    "app": "window_title",
    "window": "window_title",
    "title": "window_title",
    "recipient": "contact",
    "to": "contact",
    "who": "contact",
    "content": "message",
    "text": "message",
    "body": "message",
    "msg": "message",
    "time": "run_at",
    "at": "run_at",
    "keys": "key",
    "image": "image_ref",
    "template": "image_ref",
    "path": "image_ref",
    "times": "n",
    "count": "n",
}

IrOp = Literal[
    "activate",
    "ocr_click",
    "type",
    "key",
    "wait",
    "wait_text",
    "schedule",
    "find_image_click",
    "color_click",
    "loop",
    "if_text",
    "try_catch",
]

_IR_OPS: frozenset[str] = frozenset(
    (
        "activate",
        "ocr_click",
        "type",
        "key",
        "wait",
        "wait_text",
        "schedule",
        "find_image_click",
        "color_click",
        "loop",
        "if_text",
        "try_catch",
    )
)

# LLM hallucination aliases → closed-set opcodes (general, not task-specific).
_OP_ALIASES: dict[str, str] = {
    "open": "activate",
    "focus": "activate",
    "switch": "activate",
    "activate_window": "activate",
    "window_activate": "activate",
    "click": "ocr_click",
    "tap": "ocr_click",
    "click_text": "ocr_click",
    "ocr": "ocr_click",
    "press_text": "ocr_click",
    "type_text": "type",
    "input": "type",
    "enter_text": "type",
    "write": "type",
    "fill": "type",
    "press": "key",
    "hotkey": "key",
    "shortcut": "key",
    "key_press": "key",
    "sleep": "wait",
    "delay": "wait",
    "pause": "wait",
}

_ARG_KEY_ALIASES: dict[str, str] = {
    "url": "text",
    "query": "text",
    "q": "text",
    "href": "text",
    "title": "window",
    "app": "window",
    "window_title": "window",
}

SLOT_CLARIFY_PROMPTS: dict[str, str] = {
    "contact": "目标对象是谁/哪个会话？",
    "message": "要输入的内容是？",
    "window_title": "使用哪个应用/窗口？",
    "run_at": "什么时间执行？",
    "match_text": "要点击屏幕上的哪段文字？",
    "image_ref": "用哪张模板图定位？",
    "color": "要点击什么颜色？",
    "key": "要按哪个键？",
    "ms": "等待多少毫秒？",
    "n": "循环几次？",
}


class GoalIR(BaseModel):
    """One ordered user outcome, independent from executable block details."""

    id: str = Field(default="", description="稳定短 id，如 g1")
    action: str = Field(default="", description="模型概括的语义动作，不参与代码分支")
    target: str = Field(default="", description="动作对象；只取用户明确内容")
    value: str = Field(default="", description="输入、搜索或按键值")
    completion: str = Field(default="", description="可观察完成条件；没有则留空")
    required_ops: list[str] = Field(default_factory=list, description="实现此目标所需的执行器 opcode")
    missing: list[str] = Field(default_factory=list, description="此目标仍缺少的信息键")
    capability_gap: str = Field(default="", description="当前积木能力无法兑现的部分")


class TaskContract(BaseModel):
    """Ordered, auditable contract between the utterance and PlanIR."""

    summary: str = ""
    goals: list[GoalIR] = Field(default_factory=list)


class UnderstandIR(BaseModel):
    """Slim understand output for the LLM."""

    intent_tag: str = Field(default="other", description="兼容字段，恒为 other，不参与任务路由")
    slots: dict[str, str] = Field(
        default_factory=dict,
        description="短槽位：window_title/contact/message/run_at/schedule/…",
    )
    missing: list[str] = Field(
        default_factory=list,
        description="仍缺的槽位 id；禁止假确认",
    )
    goals: list[GoalIR] = Field(
        default_factory=list,
        description="按话术顺序列出子目标；不得把复合任务压成最后一个动作",
    )


class IrStep(BaseModel):
    """One compact plan step."""

    op: IrOp = Field(description="闭集 opcode")
    a: dict[str, str] = Field(
        default_factory=dict,
        description="短字符串参数，如 text/window/ms/slot 引用名",
    )


class PlanIR(BaseModel):
    """Slim plan for the LLM — not Flow JSON."""

    steps: list[IrStep] = Field(default_factory=list)


class IrStepDraft(BaseModel):
    """Loose step from the gateway — op is free string, coerced later."""

    op: str = Field(default="", description="opcode or alias")
    a: dict[str, str] = Field(default_factory=dict)


class PlanIRDraft(BaseModel):
    """Structured-output schema that accepts alias ops without whole-plan failure."""

    steps: list[IrStepDraft] = Field(default_factory=list)


def coerce_ir_op(op: str | None, *, args: dict[str, str] | None = None) -> str | None:
    """Map a semantics-preserving alias to a closed-set op."""
    raw = str(op or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return None
    if raw in _IR_OPS:
        return raw
    mapped = _OP_ALIASES.get(raw)
    if mapped is None:
        return None
    return mapped


def coerce_ir_args(args: dict[str, Any] | None) -> dict[str, str]:
    """Normalize arg keys; keep string values only."""
    out: dict[str, str] = {}
    for k, v in (args or {}).items():
        if v is None:
            continue
        key = str(k or "").strip()
        if not key:
            continue
        canon = _ARG_KEY_ALIASES.get(key, key)
        val = str(v).strip()
        if not val:
            continue
        if canon not in out or not out[canon]:
            out[canon] = val
    return out


def parse_plan_ir(
    raw: PlanIR | PlanIRDraft | dict[str, Any] | None,
    slots: dict[str, str] | None = None,
) -> PlanIR:
    """
    Coerce draft/dict into strict PlanIR: alias ops, drop unknown steps, then normalize.
    Never raises on bad opcodes — empty result falls through to normalize_plan_ir → slots.
    """
    if isinstance(raw, PlanIR):
        return normalize_plan_ir(raw, slots)

    data: dict[str, Any]
    if isinstance(raw, PlanIRDraft):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    else:
        return normalize_plan_ir(PlanIR(steps=[]), slots)

    coerced: list[dict[str, Any]] = []
    for st in data.get("steps") or []:
        if isinstance(st, BaseModel):
            st = st.model_dump()
        if not isinstance(st, dict):
            continue
        args = st.get("a") if isinstance(st.get("a"), dict) else {}
        if not args and isinstance(st.get("args"), dict):
            args = st["args"]
        args_n = coerce_ir_args(args)
        op = coerce_ir_op(str(st.get("op") or ""), args=args_n)
        if not op:
            continue
        coerced.append({"op": op, "a": args_n})

    return normalize_plan_ir({"steps": coerced}, slots)


def collect_unsupported_ir_ops(
    raw: PlanIR | PlanIRDraft | dict[str, Any] | None,
) -> list[str]:
    """Return non-empty op names that cannot be represented without semantic loss."""
    if isinstance(raw, BaseModel):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    else:
        return []
    unsupported: list[str] = []
    for step in data.get("steps") or []:
        if isinstance(step, BaseModel):
            step = step.model_dump()
        if not isinstance(step, dict):
            continue
        raw_op = str(step.get("op") or "").strip()
        args = step.get("a") if isinstance(step.get("a"), dict) else {}
        if raw_op and coerce_ir_op(raw_op, args=coerce_ir_args(args)) is None:
            if raw_op not in unsupported:
                unsupported.append(raw_op)
    return unsupported


class GapIR(BaseModel):
    """Optional slim gap check (code-first; LLM rarely used)."""

    ok: bool = Field(default=True)
    hints: list[str] = Field(default_factory=list)


class RepairIR(BaseModel):
    """Optional slim repair hints."""

    fixes: list[dict[str, str]] = Field(
        default_factory=list,
        description="如 [{op:set_entry},{op:connect,from:a,to:b}]",
    )


def normalize_slots(raw: dict[str, Any] | None) -> dict[str, str]:
    """Map aliases → canonical keys; drop empties; never invent values."""
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        key = str(k or "").strip()
        val = str(v).strip() if v is not None else ""
        if not key or not val:
            continue
        canon = _SLOT_ALIASES.get(key, key)
        if canon not in CANONICAL_SLOT_KEYS:
            continue
        if canon not in out or not out[canon]:
            out[canon] = val
    return out


def merge_and_normalize(
    *parts: dict[str, Any] | None,
    utterance: str = "",
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for p in parts:
        merged = merge_slots(merged, normalize_slots(p if isinstance(p, dict) else {}))
    if utterance:
        merged = merge_slots(merged, normalize_slots(extract_slots_from_utterance(utterance)))
    return normalize_slots(merged)


def missing_to_questions(missing: list[str] | None) -> list[dict[str, Any]]:
    """Turn missing slot ids into clarify UI questions (prompts from code)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in missing or []:
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        # Map aliases
        sid = _SLOT_ALIASES.get(sid, sid)
        if sid not in SLOT_CLARIFY_PROMPTS:
            continue
        seen.add(sid)
        out.append(
            {
                "id": sid,
                "prompt": SLOT_CLARIFY_PROMPTS[sid],
                "choices": [],
                "allow_free_text": True,
            }
        )
    return out


def plan_ir_to_dict(plan: PlanIR | dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {"steps": []}
    if isinstance(plan, PlanIR):
        return plan.model_dump()
    if isinstance(plan, dict):
        try:
            return PlanIR.model_validate(plan).model_dump()
        except Exception:
            steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
            return {"steps": steps}
    return {"steps": []}


def format_ir_for_prompt(plan: PlanIR | dict[str, Any] | None) -> str:
    """One-line-per-step compact serialization for prompts/logs."""
    data = plan_ir_to_dict(plan)
    lines: list[str] = []
    for i, step in enumerate(data.get("steps") or [], 1):
        if not isinstance(step, dict):
            continue
        op = str(step.get("op") or "")
        args = step.get("a") if isinstance(step.get("a"), dict) else {}
        if not args and isinstance(step.get("args"), dict):
            args = step["args"]
        arg_s = ",".join(f"{k}={v}" for k, v in list(args.items())[:6] if v)
        lines.append(f"{i}.{op}" + (f":{arg_s}" if arg_s else ""))
    return "\n".join(lines) if lines else "(empty)"


def plan_ir_from_slots(
    intent: str,
    slots: dict[str, str] | None,
    *,
    utterance: str = "",
) -> PlanIR:
    """Weak slot→op projection for empty LLM plans. No task-type macros."""
    s = merge_and_normalize(slots, utterance=utterance or intent)
    steps: list[IrStep] = []

    if s.get("run_at") or str(s.get("schedule") or "").lower() in ("true", "1", "yes"):
        steps.append(IrStep(op="schedule", a={"run_at": s.get("run_at") or ""}))
    if s.get("window_title"):
        steps.append(IrStep(op="activate", a={"window": s["window_title"]}))
    if s.get("match_text"):
        steps.append(IrStep(op="ocr_click", a={"text": s["match_text"]}))
    elif s.get("contact"):
        steps.append(IrStep(op="ocr_click", a={"text": s["contact"]}))
    if s.get("message"):
        steps.append(IrStep(op="type", a={"text": s["message"]}))
    if s.get("key"):
        steps.append(IrStep(op="key", a={"keys": s["key"]}))
    if s.get("ms"):
        steps.append(IrStep(op="wait", a={"ms": s["ms"]}))
    if s.get("image_ref"):
        steps.append(IrStep(op="find_image_click", a={"image_ref": s["image_ref"]}))
    if s.get("color"):
        steps.append(IrStep(op="color_click", a={"color": s["color"]}))
    return PlanIR(steps=steps)


def _step_fingerprint(st: IrStep) -> tuple[str, tuple[tuple[str, str], ...]]:
    a = {
        str(k): str(v)
        for k, v in (st.a or {}).items()
        if v is not None and str(v).strip()
    }
    # Treat window / window_title as the same for dedupe
    if "window_title" in a and "window" not in a:
        a["window"] = a.pop("window_title")
    return (str(st.op), tuple(sorted(a.items())))


def _dedupe_consecutive_steps(steps: list[IrStep]) -> list[IrStep]:
    out: list[IrStep] = []
    prev: tuple[str, tuple[tuple[str, str], ...]] | None = None
    for st in steps:
        fp = _step_fingerprint(st)
        if fp == prev:
            continue
        out.append(st)
        prev = fp
    return out


def _dedupe_repeated_setup(steps: list[IrStep], slots: dict[str, str]) -> list[IrStep]:
    """Drop repeated activate before the first type (LLM stutter)."""
    window = str(slots.get("window_title") or "").strip()
    seen_activate_windows: set[str] = set()
    out: list[IrStep] = []
    typed = False
    for st in steps:
        if st.op == "type":
            typed = True
            out.append(st)
            continue
        if not typed and st.op == "activate":
            w = str(st.a.get("window") or st.a.get("window_title") or window or "").strip()
            if w and w in seen_activate_windows:
                continue
            if w:
                seen_activate_windows.add(w)
            out.append(st)
            continue
        out.append(st)
    return out


def normalize_plan_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
) -> PlanIR:
    """Parse PlanIR steps; empty plans fall back to generic slot projection."""
    s = normalize_slots(slots)
    data = plan_ir_to_dict(plan)
    raw_steps = list(data.get("steps") or [])
    if not raw_steps:
        return plan_ir_from_slots("", s)

    out: list[IrStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip()
        args = raw.get("a") if isinstance(raw.get("a"), dict) else {}
        if not args and isinstance(raw.get("args"), dict):
            args = {str(k): str(v) for k, v in raw["args"].items() if v is not None}
        else:
            args = {str(k): str(v) for k, v in args.items() if v is not None}
        if not op or op not in _IR_OPS:
            continue
        try:
            out.append(IrStep(op=op, a=args))  # type: ignore[arg-type]
        except Exception:
            continue
    if not out:
        return plan_ir_from_slots("", s)

    out = _dedupe_consecutive_steps(out)
    out = _dedupe_repeated_setup(out, s)
    return PlanIR(steps=out)


def plan_ir_to_outline(
    plan: PlanIR | dict[str, Any] | None,
    *,
    summary: str = "",
    slots: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Project PlanIR → legacy PlanOutline dict for UI / outline_build."""
    plan_n = normalize_plan_ir(plan, slots)
    steps: list[dict[str, Any]] = []
    for i, st in enumerate(plan_n.steps, 1):
        op = st.op
        a = dict(st.a or {})
        hint = ""
        sense = "none"
        match_text = None
        params: dict[str, Any] = {}
        goal = op

        if op == "activate":
            hint = "window_activate"
            params["title"] = a.get("window") or a.get("window_title") or a.get("title") or ""
            goal = f"激活窗口 {params['title']}".strip()
        elif op == "ocr_click":
            hint = "ocr_click"
            sense = "ocr"
            match_text = a.get("text") or a.get("match_text") or ""
            # Resolve slot ref names like "contact"
            if match_text in CANONICAL_SLOT_KEYS:
                match_text = a.get("text") or match_text
            params["window_title"] = a.get("window") or a.get("window_title") or ""
            goal = f"点击 {match_text}".strip()
        elif op == "type":
            hint = "type_text"
            params["text"] = a.get("text") or a.get("message") or ""
            goal = "输入文本"
        elif op == "key":
            hint = "key_press"
            params["key"] = a.get("keys") or a.get("key") or "enter"
            goal = "按键"
        elif op == "wait":
            hint = "delay"
            params["ms"] = a.get("ms") or "1000"
            goal = "等待"
        elif op == "wait_text":
            hint = "wait_until"
            sense = "ocr"
            match_text = a.get("text") or ""
            params["expect_text"] = match_text
            goal = f"等待文字 {match_text}".strip()
        elif op == "schedule":
            hint = "schedule_trigger"
            params["run_at"] = a.get("run_at") or ""
            goal = "定时触发"
        elif op == "find_image_click":
            hint = "find_image_click"
            params["path"] = a.get("image_ref") or a.get("path") or ""
            goal = "找图点击"
        elif op == "color_click":
            hint = "color_click"
            params["color"] = a.get("color") or ""
            goal = "颜色点击"
        elif op == "loop":
            hint = "loop_n"
            params["times"] = a.get("n") or a.get("times") or "3"
            goal = "循环"
        elif op == "if_text":
            hint = "if_text"
            sense = "ocr"
            match_text = a.get("text") or ""
            params["match_text"] = match_text
            goal = "文字分支"
        elif op == "try_catch":
            hint = "try_catch"
            goal = "容错"
        else:
            hint = op
            params = dict(a)
            goal = op

        steps.append(
            {
                "id": f"s{i}",
                "goal": goal,
                "block_hint": hint,
                "needs_sense": sense,
                "match_text": match_text,
                "params": params,
                "note": "",
            }
        )
    return {"summary": summary or "", "steps": steps}


def _normalize_goal(raw: GoalIR | dict[str, Any], index: int) -> GoalIR:
    data = raw.model_dump() if isinstance(raw, GoalIR) else dict(raw or {})
    requested_ops = [
        str(op).strip()
        for op in (data.get("required_ops") or [])
        if str(op).strip()
    ]
    supported_ops = [op for op in requested_ops if op in _IR_OPS]
    unsupported_ops = [op for op in requested_ops if op not in _IR_OPS]
    gap = str(data.get("capability_gap") or "").strip()
    if unsupported_ops and not gap:
        gap = f"执行器不支持 opcode：{', '.join(unsupported_ops)}"
    return GoalIR(
        id=str(data.get("id") or f"g{index}"),
        action=str(data.get("action") or "").strip(),
        target=str(data.get("target") or "").strip(),
        value=str(data.get("value") or "").strip(),
        completion=str(data.get("completion") or "").strip(),
        required_ops=supported_ops,
        missing=[str(item) for item in (data.get("missing") or []) if str(item)],
        capability_gap=gap,
    )


def build_task_contract(
    utterance: str,
    goals: list[GoalIR] | list[dict[str, Any]] | None = None,
) -> TaskContract:
    """Build the ordered user-outcome contract used by gap and validation."""
    normalized = [
        _normalize_goal(goal, i)
        for i, goal in enumerate(goals or [], 1)
        if isinstance(goal, (GoalIR, dict))
    ]
    return TaskContract(summary=str(utterance or "")[:160], goals=normalized)


def reconcile_intent_tag(
    intent_tag: str,
    contract: TaskContract | dict[str, Any] | None,
    *,
    utterance: str = "",
) -> str:
    """Make legacy intent tags non-authoritative when ordered goals exist."""
    tag = str(intent_tag or "other").strip()
    if task_contract_to_dict(contract).get("goals"):
        return "other"
    return tag


def task_contract_to_dict(
    contract: TaskContract | dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(contract, TaskContract):
        return contract.model_dump()
    if isinstance(contract, dict):
        try:
            return TaskContract.model_validate(contract).model_dump()
        except Exception:
            pass
    return TaskContract().model_dump()


def evaluate_task_coverage(
    contract: TaskContract | dict[str, Any] | None,
    plan: PlanIR | dict[str, Any] | None,
) -> dict[str, Any]:
    """Check ordered goal requirements against the executable IR sequence."""
    contract_n = TaskContract.model_validate(task_contract_to_dict(contract))
    ops = [st.op for st in normalize_plan_ir(plan, {}).steps]
    cursor = 0
    goals: list[dict[str, Any]] = []
    missing: list[str] = []
    capability_gaps: list[str] = []
    for goal in contract_n.goals:
        matched: list[int] = []
        local_cursor = cursor
        goal_missing: list[str] = []
        if not goal.required_ops and not goal.capability_gap and not goal.missing:
            missing.append(f"目标 {goal.id} 未声明所需执行器能力")
        for required in goal.required_ops:
            found = next(
                (i for i in range(local_cursor, len(ops)) if ops[i] == required),
                None,
            )
            if found is None:
                goal_missing.append(required)
            else:
                matched.append(found)
                local_cursor = found + 1
        if not goal_missing:
            cursor = local_cursor
        else:
            missing.append(
                f"目标 {goal.id}({goal.action}) 缺少动作：{', '.join(goal_missing)}"
            )
        if goal.capability_gap:
            capability_gaps.append(f"目标 {goal.id}：{goal.capability_gap}")
        goals.append(
            {
                "id": goal.id,
                "action": goal.action,
                "covered": not goal_missing,
                "matched_steps": [i + 1 for i in matched],
                "missing_ops": goal_missing,
            }
        )
    return {
        "complete": not missing,
        "goals": goals,
        "missing": missing,
        "capability_gaps": capability_gaps,
    }


def validate_plan_draft(
    plan: PlanIR | dict[str, Any] | None,
    draft: dict[str, Any] | None,
) -> list[str]:
    """Validate that each simple IR action has a corresponding draft block chain."""
    node_map = (draft or {}).get("nodes")
    nodes = node_map if isinstance(node_map, dict) else {}
    available = [str(node.get("type") or "") for node in nodes.values() if isinstance(node, dict)]
    expected_by_op = {
        "activate": ["window_activate"],
        "ocr_click": ["ocr_recognize", "click"],
        "type": ["type_text"],
        "key": ["key_press"],
        "wait": ["delay"],
        "wait_text": ["wait_until"],
        "schedule": ["schedule_trigger"],
        "find_image_click": ["find_image", "click"],
        "color_click": ["color_detect", "click"],
        "loop": ["loop_n"],
        "if_text": ["if_text_contains"],
        "try_catch": ["try_catch"],
    }
    remaining = list(available)
    errors: list[str] = []
    for index, step in enumerate(normalize_plan_ir(plan, {}).steps, 1):
        for expected in expected_by_op.get(step.op, []):
            if expected in remaining:
                remaining.remove(expected)
            else:
                errors.append(f"IR 第 {index} 步 {step.op} 未生成节点 {expected}")
    return errors


def plan_ir_looks_weak(
    plan: PlanIR | dict[str, Any] | None,
    *,
    utterance: str = "",
    task_contract: TaskContract | dict[str, Any] | None = None,
) -> bool:
    data = plan_ir_to_dict(plan)
    steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return True
    ops = {str(s.get("op") or "").lower() for s in steps}
    useful = ops - {"", "wait"}
    if not useful:
        return True
    contract = task_contract or build_task_contract(utterance)
    coverage = evaluate_task_coverage(contract, plan)
    if task_contract_to_dict(contract).get("goals") and not coverage["complete"]:
        return True
    return False


def gap_from_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
    *,
    intent: str = "",
    task_contract: TaskContract | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Code-first gap check against PlanIR + slots."""
    s = normalize_slots(slots)
    plan_n = normalize_plan_ir(plan, s)
    missing: list[str] = []

    if not plan_n.steps:
        missing.append("大纲无步骤")

    contract = task_contract or build_task_contract(intent)
    coverage = evaluate_task_coverage(contract, plan_n)
    missing.extend(str(item) for item in coverage.get("missing") or [])
    missing = list(dict.fromkeys(missing))

    return {
        "complete": not missing,
        "missing": missing,
        "hints": missing,
        "coverage": coverage,
        "capability_gaps": list(coverage.get("capability_gaps") or []),
    }


def infer_missing_slots(
    intent_tag: str,
    slots: dict[str, str],
    *,
    utterance: str = "",
) -> list[str]:
    """Deprecated: missing slots come from UnderstandIR/goals, not keyword task rules."""
    del intent_tag, slots, utterance
    return []
