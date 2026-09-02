"""Compact Agent IR: slim LLM-facing schemas + normalization + slot→plan helpers.

LLM outputs decision bits only; ir_compile expands into real draft nodes.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.core.ai.graphs.slot_extract import extract_slots_from_utterance, merge_slots

_NULLISH_GAPS = frozenset(
    {
        "",
        "none",
        "null",
        "nil",
        "n/a",
        "na",
        "无",
        "无缺口",
        "ok",
        "false",
        "0",
        "capability_gap",
        "capabilability_gap",
    }
)
_PLACEHOLDER_GOAL_RE = re.compile(
    r"^(action|target|value|goal|id|completion|completion_step)"
    r"(?:_+\d*|_+\s*_+\d*|_\d+)$",
    re.IGNORECASE,
)

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

    @field_validator("goals", mode="before")
    @classmethod
    def _coerce_goals(cls, value: Any) -> list[Any]:
        """Accept bare strings (common LLM slip) as GoalIR.action."""
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        out: list[Any] = []
        for i, item in enumerate(value, 1):
            if isinstance(item, str):
                text = item.strip()
                if text:
                    out.append({"id": f"g{i}", "action": text})
                continue
            out.append(item)
        return out


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


def coerce_ir_op(op: str | None, *, args: dict[str, str] | None = None) -> str | None:
    """Map a semantics-preserving alias to a closed-set op."""
    del args  # reserved for future disambiguation
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


def coerce_step_a_value(op: str | None, raw_a: Any) -> dict[str, Any]:
    """Lift bare-string step args (common LLM slip) into an object keyed by op."""
    if isinstance(raw_a, dict):
        return dict(raw_a)
    if raw_a is None:
        return {}
    text = str(raw_a).strip()
    if not text:
        return {}
    canon = coerce_ir_op(op) or str(op or "").strip().lower().replace("-", "_")
    if canon == "activate":
        return {"window": text}
    if canon == "key":
        return {"keys": text}
    if canon == "wait":
        return {"ms": text}
    if canon == "schedule":
        return {"run_at": text}
    if canon == "find_image_click":
        return {"image_ref": text}
    if canon == "color_click":
        return {"color": text}
    if canon == "loop":
        return {"n": text}
    # ocr_click / type / wait_text / if_text / default
    return {"text": text}


def _normalize_step_args_for_op(op: str, args: dict[str, str]) -> dict[str, str]:
    """Op-specific arg cleanup (e.g. key text/key → keys)."""
    a = dict(args or {})
    if op == "key":
        keys = a.get("keys") or a.get("key") or a.get("text") or ""
        if keys:
            a = {"keys": keys}
    if op == "activate":
        window = a.get("window") or a.get("window_title") or a.get("title") or ""
        if window:
            a = {**a, "window": window}
    return a


class IrStepDraft(BaseModel):
    """Loose step from the gateway — op is free string, coerced later."""

    op: str = Field(default="", description="opcode or alias")
    a: dict[str, str] = Field(default_factory=dict)

    @field_validator("a", mode="before")
    @classmethod
    def _coerce_a(cls, value: Any, info: Any = None) -> Any:
        op = ""
        if info is not None and getattr(info, "data", None):
            op = str(info.data.get("op") or "")
        if isinstance(value, dict):
            return value
        return coerce_step_a_value(op, value)


class PlanIRDraft(BaseModel):
    """Structured-output schema that accepts alias ops without whole-plan failure."""

    steps: list[IrStepDraft] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def _coerce_steps(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                op = str(item.get("op") or "")
                a = item.get("a", item.get("args"))
                if not isinstance(a, dict):
                    item = {**item, "a": coerce_step_a_value(op, a)}
                out.append(item)
            else:
                out.append(item)
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
        op_raw = str(st.get("op") or "")
        raw_a = st.get("a")
        if raw_a is None and "args" in st:
            raw_a = st.get("args")
        if not isinstance(raw_a, dict):
            raw_a = coerce_step_a_value(op_raw, raw_a)
        args_n = coerce_ir_args(raw_a)
        op = coerce_ir_op(op_raw, args=args_n)
        if not op:
            continue
        args_n = _normalize_step_args_for_op(op, args_n)
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
        raw_a = step.get("a")
        if not isinstance(raw_a, dict):
            raw_a = coerce_step_a_value(raw_op, raw_a)
        args = coerce_ir_args(raw_a)
        if raw_op and coerce_ir_op(raw_op, args=args) is None:
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
    # 宽松 schema（PlanIRDraft 等）：先严格校验，失败则透传原始步骤供
    # normalize_plan_ir 做别名/参数归一。此前静默返回空步骤，会整段丢弃
    # 合法的别名输出。
    data = plan.model_dump() if hasattr(plan, "model_dump") else {}
    if not isinstance(data, dict):
        return {"steps": []}
    try:
        return PlanIR.model_validate(data).model_dump()
    except Exception:
        steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        return {"steps": steps}


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
        op_raw = str(raw.get("op") or "").strip()
        raw_a = raw.get("a")
        if raw_a is None and isinstance(raw.get("args"), dict):
            raw_a = raw["args"]
        if not isinstance(raw_a, dict):
            raw_a = coerce_step_a_value(op_raw, raw_a)
        args = coerce_ir_args(raw_a)
        op = coerce_ir_op(op_raw, args=args) or (op_raw if op_raw in _IR_OPS else "")
        if not op or op not in _IR_OPS:
            continue
        args = _normalize_step_args_for_op(op, args)
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


def _normalize_capability_gap(raw: Any) -> str:
    gap = str(raw or "").strip()
    if gap.lower() in _NULLISH_GAPS:
        return ""
    return gap


def _strip_template_refs(raw: Any) -> str:
    """Drop draft-template junk like {{ocr_recognize_xxx.x}} from goal fields."""
    text = str(raw or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"\{\{[^{}]+\}\}", "", text)
    cleaned = re.sub(r"\s*,\s*", ",", cleaned).strip(" ,")
    return cleaned.strip()


def _is_placeholder_goal_text(raw: Any) -> bool:
    text = str(raw or "").strip()
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"_+", "_", compact)
    return bool(_PLACEHOLDER_GOAL_RE.fullmatch(compact))


def _goal_has_signal(goal: GoalIR) -> bool:
    """Drop LLM placeholder noise like action_4 / target_4 / capabilability_gap."""
    real_fields = [
        goal.action,
        goal.target,
        goal.value,
        goal.completion,
    ]
    if any(not _is_placeholder_goal_text(v) for v in real_fields if str(v or "").strip()):
        return True
    if goal.required_ops:
        return True
    if goal.missing:
        return True
    if goal.capability_gap:
        return True
    return False


def _coerce_required_ops(raw_ops: list[Any] | None) -> tuple[list[str], list[str]]:
    """Map block-name aliases → IR ops; return (supported, truly_unsupported)."""
    supported: list[str] = []
    unsupported: list[str] = []
    for op in raw_ops or []:
        token = str(op or "").strip()
        if not token:
            continue
        canon = coerce_ir_op(token)
        if canon and canon in _IR_OPS:
            if canon not in supported:
                supported.append(canon)
        else:
            if token not in unsupported:
                unsupported.append(token)
    return supported, unsupported


def _infer_required_ops(action: str, target: str, value: str, completion: str) -> list[str]:
    """Light keyword projection when the model omits required_ops."""
    blob = " ".join([action, target, value, completion]).lower()
    ops: list[str] = []

    def add(op: str) -> None:
        if op not in ops:
            ops.append(op)

    if any(k in blob for k in ("activate", "open", "focus", "打开", "激活", "启动")):
        add("activate")
    if any(
        k in blob
        for k in (
            "ocr_click",
            "click",
            "select",
            "tap",
            "点击",
            "选择",
            "通讯录",
            "联系人",
        )
    ):
        add("ocr_click")
    if any(k in blob for k in ("type", "input", "输入", "填写")):
        add("type")
    if any(k in blob for k in ("key", "press", "enter", "回车", "热键")):
        add("key")
    if any(k in blob for k in ("send", "发送", "消息")):
        if value or "type" in ops or any(k in blob for k in ("type", "input", "输入")):
            add("type")
        add("key")
    if any(k in blob for k in ("wait_text", "等待文字")):
        add("wait_text")
    elif any(k in blob for k in ("wait", "delay", "等待")):
        add("wait")
    if any(k in blob for k in ("schedule", "定时", "预约")):
        add("schedule")
    if any(k in blob for k in ("find_image", "找图", "模板")):
        add("find_image_click")
    if any(k in blob for k in ("color", "颜色")):
        add("color_click")
    if any(k in blob for k in ("loop", "循环")):
        add("loop")
    if any(k in blob for k in ("if_text", "分支", "如果")):
        add("if_text")
    return ops


def _goal_targets_compatible(
    goal: GoalIR,
    prev_target: str,
    prev_value: str,
) -> bool:
    """True when consecutive same-op goals can share one IR step."""
    cur_t = (goal.target or "").strip().lower()
    cur_v = (goal.value or "").strip().lower()
    prev_t = (prev_target or "").strip().lower()
    prev_v = (prev_value or "").strip().lower()
    if not cur_t and not cur_v:
        return True
    if not prev_t and not prev_v:
        return True
    if cur_t and prev_t and (cur_t == prev_t or cur_t in prev_t or prev_t in cur_t):
        return True
    if cur_v and prev_v and cur_v == prev_v:
        return True
    if cur_t and prev_v and cur_t == prev_v:
        return True
    if cur_v and prev_t and cur_v == prev_t:
        return True
    return False


def _normalize_goal(raw: GoalIR | dict[str, Any] | str, index: int) -> GoalIR | None:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        data: dict[str, Any] = {"id": f"g{index}", "action": text}
    elif isinstance(raw, GoalIR):
        data = raw.model_dump()
    else:
        data = dict(raw or {})
    supported_ops, unsupported_ops = _coerce_required_ops(data.get("required_ops"))
    gap = _normalize_capability_gap(data.get("capability_gap"))
    # Recover aliases previously parked in "执行器不支持 opcode：window_activate, …"
    gap_match = re.match(r"^执行器不支持 opcode：(.+)$", gap)
    if gap_match:
        recovered, still_bad = _coerce_required_ops(
            [p.strip() for p in gap_match.group(1).split(",") if p.strip()]
        )
        for op in recovered:
            if op not in supported_ops:
                supported_ops.append(op)
        gap = (
            f"执行器不支持 opcode：{', '.join(still_bad)}" if still_bad else ""
        )
    if unsupported_ops and not gap:
        gap = f"执行器不支持 opcode：{', '.join(unsupported_ops)}"
    action = _strip_template_refs(data.get("action"))
    target = _strip_template_refs(data.get("target"))
    value = _strip_template_refs(data.get("value"))
    completion = _strip_template_refs(data.get("completion"))
    if _is_placeholder_goal_text(action):
        action = ""
    if _is_placeholder_goal_text(target):
        target = ""
    if _is_placeholder_goal_text(value):
        value = ""
    if _is_placeholder_goal_text(completion):
        completion = ""
    if not supported_ops and not gap:
        supported_ops = _infer_required_ops(action, target, value, completion)
    goal = GoalIR(
        id=str(data.get("id") or f"g{index}"),
        action=action,
        target=target,
        value=value,
        completion=completion,
        required_ops=supported_ops,
        missing=[str(item) for item in (data.get("missing") or []) if str(item)],
        capability_gap=gap,
    )
    if not _goal_has_signal(goal):
        return None
    if not goal.action and (goal.target or goal.value):
        goal.action = goal.target or goal.value
    return goal


def build_task_contract(
    utterance: str,
    goals: list[GoalIR] | list[dict[str, Any]] | list[Any] | None = None,
) -> TaskContract:
    """Build the ordered user-outcome contract used by gap and validation."""
    normalized: list[GoalIR] = []
    for i, goal in enumerate(goals or [], 1):
        if not isinstance(goal, (GoalIR, dict, str)):
            continue
        item = _normalize_goal(goal, i)
        if item is not None:
            normalized.append(item)
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
    *,
    utterance: str = "",
) -> dict[str, Any]:
    """Check ordered goal requirements against the executable IR sequence."""
    contract_n = TaskContract.model_validate(task_contract_to_dict(contract))
    plan_steps = normalize_plan_ir(plan, {}).steps
    ops = [st.op for st in plan_steps]
    useful_ops = [op for op in ops if op and op != "wait"]
    cursor = 0
    goals: list[dict[str, Any]] = []
    missing: list[str] = []
    soft_warnings: list[str] = []
    capability_gaps: list[str] = []
    summary = str(contract_n.summary or utterance or "").strip()
    if summary and not contract_n.goals:
        missing.append("缺少任务目标")
    prev_last_idx: int | None = None
    prev_last_op = ""
    prev_target = ""
    prev_value = ""
    for goal in contract_n.goals:
        matched: list[int] = []
        local_cursor = cursor
        goal_missing: list[str] = []
        if not goal.required_ops and not goal.capability_gap and not goal.missing:
            msg = f"目标 {goal.id} 未声明所需执行器能力"
            if useful_ops:
                soft_warnings.append(msg)
            else:
                missing.append(msg)
        for required in goal.required_ops:
            reused = False
            if (
                prev_last_idx is not None
                and prev_last_op == required
                and _goal_targets_compatible(goal, prev_target, prev_value)
                and not matched
                and 0 <= prev_last_idx < len(ops)
                and ops[prev_last_idx] == required
            ):
                matched.append(prev_last_idx)
                local_cursor = max(local_cursor, prev_last_idx + 1)
                reused = True
            if reused:
                continue
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
            if matched:
                prev_last_idx = matched[-1]
                prev_last_op = ops[prev_last_idx]
                prev_target = goal.target
                prev_value = goal.value
        else:
            missing.append(
                f"目标 {goal.id}({goal.action}) 缺少动作：{', '.join(goal_missing)}"
            )
        if goal.capability_gap:
            capability_gaps.append(f"目标 {goal.id}：{goal.capability_gap}")
        covered = not goal_missing and (
            bool(matched)
            or bool(goal.capability_gap)
            or bool(goal.missing)
            or (not goal.required_ops and bool(useful_ops))
        )
        if (
            not goal.required_ops
            and not goal.capability_gap
            and not goal.missing
            and not useful_ops
        ):
            covered = False
        goals.append(
            {
                "id": goal.id,
                "action": goal.action,
                "covered": covered,
                "matched_steps": [i + 1 for i in matched],
                "missing_ops": goal_missing,
            }
        )
    return {
        "complete": not missing and not capability_gaps,
        "goals": goals,
        "missing": missing,
        "capability_gaps": capability_gaps,
        "soft_warnings": soft_warnings,
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
    """True when PlanIR has no useful executable steps (SSOT-only; ignores goals)."""
    del utterance, task_contract
    data = plan_ir_to_dict(plan)
    steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return True
    ops = {str(s.get("op") or "").lower() for s in steps}
    useful = ops - {"", "wait"}
    return not useful


def _plan_step_missing_args(
    step: IrStep,
    slots: dict[str, str],
) -> str | None:
    """Return a hard missing message if SSOT step lacks required args after slots."""
    a = dict(step.a or {})
    if step.op == "activate":
        if not (a.get("window") or slots.get("window_title")):
            return "activate 缺少 window"
    elif step.op == "ocr_click":
        if not (
            a.get("text")
            or slots.get("match_text")
            or slots.get("contact")
        ):
            return "ocr_click 缺少 text"
    elif step.op == "type":
        if not (a.get("text") or slots.get("message")):
            return "type 缺少 text"
    elif step.op == "key":
        if not (a.get("keys") or a.get("key") or slots.get("key")):
            return "key 缺少 keys"
    elif step.op == "find_image_click":
        if not (a.get("image_ref") or slots.get("image_ref")):
            return "find_image_click 缺少 image_ref"
    elif step.op == "color_click":
        if not (a.get("color") or slots.get("color")):
            return "color_click 缺少 color"
    return None


def derive_goals_from_plan_ir(
    plan: PlanIR | dict[str, Any] | None,
    utterance: str = "",
    *,
    slots: dict[str, str] | None = None,
) -> TaskContract:
    """Derive display-only goals from SSOT PlanIR (never authoritative for gap)."""
    plan_n = normalize_plan_ir(plan, slots)
    goals: list[GoalIR] = []
    for i, st in enumerate(plan_n.steps, 1):
        a = dict(st.a or {})
        target = (
            a.get("window")
            or a.get("text")
            or a.get("keys")
            or a.get("image_ref")
            or a.get("color")
            or ""
        )
        value = a.get("text") if st.op == "type" else (a.get("keys") if st.op == "key" else "")
        goals.append(
            GoalIR(
                id=f"g{i}",
                action=st.op,
                target=target,
                value=value or "",
                required_ops=[st.op],
            )
        )
    return TaskContract(summary=str(utterance or "")[:160], goals=goals)


def gap_from_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
    *,
    intent: str = "",
    task_contract: TaskContract | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Code-first gap check against SSOT PlanIR + slots only (goals are soft)."""
    s = normalize_slots(slots)
    plan_n = normalize_plan_ir(plan, s)
    missing: list[str] = []

    if not plan_n.steps:
        missing.append("大纲无步骤")
    for index, step in enumerate(plan_n.steps, 1):
        msg = _plan_step_missing_args(step, s)
        if msg:
            missing.append(f"第 {index} 步 {msg}")
    missing = list(dict.fromkeys(missing))

    # Coverage vs LLM goals is display/soft only — never blocks SSOT complete.
    contract = task_contract or derive_goals_from_plan_ir(plan_n, intent, slots=s)
    coverage = evaluate_task_coverage(contract, plan_n, utterance=intent)
    soft_warnings = list(coverage.get("soft_warnings") or [])
    soft_warnings.extend(str(item) for item in coverage.get("missing") or [])
    soft_warnings.extend(str(item) for item in coverage.get("capability_gaps") or [])
    soft_warnings = list(dict.fromkeys(soft_warnings))

    return {
        "complete": not missing,
        "missing": missing,
        "hints": missing,
        "coverage": coverage,
        "capability_gaps": [],
        "soft_warnings": soft_warnings,
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
