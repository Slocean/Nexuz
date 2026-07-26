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

IntentTag = Literal[
    "send_message",
    "type_text",
    "click_text",
    "wait",
    "schedule",
    "window",
    "find_image",
    "color_click",
    "loop",
    "branch",
    "other",
]

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
    "send_im",
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
        "send_im",
    )
)

# LLM hallucination aliases → closed-set opcodes (general, not task-specific).
_OP_ALIASES: dict[str, str] = {
    "open": "activate",
    "launch": "activate",
    "start": "activate",
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
    "search": "type",
    "press": "key",
    "hotkey": "key",
    "shortcut": "key",
    "key_press": "key",
    "sleep": "wait",
    "delay": "wait",
    "pause": "wait",
    "goto": "type",
    "navigate": "type",
    "open_url": "type",
    "browse": "type",
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
    "contact": "发给哪位联系人？",
    "message": "要发送什么内容？",
    "window_title": "使用哪个应用/窗口？",
    "run_at": "什么时间执行？",
    "match_text": "要点击屏幕上的哪段文字？",
    "image_ref": "用哪张模板图定位？",
    "color": "要点击什么颜色？",
    "key": "要按哪个键？",
    "ms": "等待多少毫秒？",
    "n": "循环几次？",
}


class UnderstandIR(BaseModel):
    """Slim understand output for the LLM."""

    intent_tag: IntentTag = Field(default="other", description="意图标签")
    slots: dict[str, str] = Field(
        default_factory=dict,
        description="短槽位：window_title/contact/message/run_at/schedule/…",
    )
    missing: list[str] = Field(
        default_factory=list,
        description="仍缺的槽位 id，如 contact/message；禁止假确认",
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
    """
    Map alias → closed-set op. Return None to drop the step (unknown / empty search).
    `search` only maps to type when there is text-like content in args.
    """
    raw = str(op or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return None
    if raw in _IR_OPS:
        return raw
    mapped = _OP_ALIASES.get(raw)
    if mapped is None:
        return None
    if raw == "search":
        a = args or {}
        has_text = any(
            str(a.get(k) or "").strip()
            for k in ("text", "query", "q", "url", "href", "message")
        )
        if not has_text:
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


def expand_send_im_steps(slots: dict[str, str]) -> list[IrStep]:
    """Deterministic IM send macro from slots — no invented contacts."""
    steps: list[IrStep] = []
    if slots.get("run_at") or str(slots.get("schedule") or "").lower() in (
        "true",
        "1",
        "yes",
    ):
        steps.append(IrStep(op="schedule", a={"run_at": slots.get("run_at") or ""}))
    if slots.get("window_title"):
        steps.append(IrStep(op="activate", a={"window": slots["window_title"]}))
    if slots.get("contact"):
        steps.append(IrStep(op="ocr_click", a={"text": slots["contact"]}))
    if slots.get("message"):
        steps.append(IrStep(op="type", a={"text": slots["message"]}))
        steps.append(IrStep(op="ocr_click", a={"text": "发送"}))
    return steps


def plan_ir_from_slots(
    intent: str,
    slots: dict[str, str] | None,
    *,
    utterance: str = "",
) -> PlanIR:
    """Offline PlanIR from normalized slots — never invents contacts/apps."""
    s = merge_and_normalize(slots, utterance=utterance or intent)
    steps: list[IrStep] = []

    # Prefer send_im expansion when messaging slots present
    if s.get("contact") and s.get("message"):
        return PlanIR(steps=expand_send_im_steps(s))

    if s.get("run_at") or str(s.get("schedule") or "").lower() in ("true", "1", "yes"):
        steps.append(IrStep(op="schedule", a={"run_at": s.get("run_at") or ""}))
    if s.get("window_title"):
        steps.append(IrStep(op="activate", a={"window": s["window_title"]}))
    if s.get("match_text") or s.get("contact"):
        steps.append(
            IrStep(
                op="ocr_click",
                a={"text": s.get("match_text") or s.get("contact") or ""},
            )
        )
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

    if not steps:
        import re

        typed = s.get("message") or ""
        if not typed:
            m = re.search(
                r"(?:输入|键入|打字)\s*[「\"'『]?([^」\"'』\n]{1,80})",
                intent or utterance or "",
            )
            if m:
                typed = m.group(1).strip()
        if typed:
            steps = [
                IrStep(op="wait", a={"ms": "500"}),
                IrStep(op="type", a={"text": typed}),
            ]
        # else: leave empty — do not invent a delay-only placeholder plan
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
    """Drop repeated activate / contact ocr_click before the first type (LLM stutter)."""
    contact = str(slots.get("contact") or "").strip()
    window = str(slots.get("window_title") or "").strip()
    seen_activate_windows: set[str] = set()
    seen_contact_click = False
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
        if not typed and st.op == "ocr_click":
            text = str(st.a.get("text") or "").strip()
            if contact and text == contact:
                if seen_contact_click:
                    continue
                seen_contact_click = True
            out.append(st)
            continue
        out.append(st)
    return out


def _should_use_canonical_send(steps: list[IrStep], slots: dict[str, str]) -> bool:
    """When slots already define a send, prefer canonical 4-step if LLM plan is redundant."""
    if not (slots.get("contact") and slots.get("message")):
        return False
    ops = [st.op for st in steps]
    if "type" not in ops:
        return False
    fps = [_step_fingerprint(st) for st in steps]
    if len(fps) != len(set(fps)):
        return True
    canonical = expand_send_im_steps(slots)
    if len(steps) > len(canonical) + 1:
        return True
    return False


def normalize_plan_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
) -> PlanIR:
    """Expand send_im / empty plans; dedupe LLM stutter; canonicalize send when slots ready."""
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
        if op == "send_im":
            out.extend(expand_send_im_steps(s))
            continue
        if not op:
            continue
        try:
            out.append(IrStep(op=op, a=args))  # type: ignore[arg-type]
        except Exception:
            continue
    if not out:
        return plan_ir_from_slots("", s)

    out = _dedupe_consecutive_steps(out)
    out = _dedupe_repeated_setup(out, s)
    if _should_use_canonical_send(out, s):
        return PlanIR(steps=expand_send_im_steps(s))
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
        elif op == "send_im":
            # Should have been expanded; skip
            continue
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


def plan_ir_looks_weak(plan: PlanIR | dict[str, Any] | None) -> bool:
    data = plan_ir_to_dict(plan)
    steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return True
    ops = {str(s.get("op") or "").lower() for s in steps}
    useful = ops - {"", "wait"}
    return not useful


def gap_from_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
    *,
    intent: str = "",
) -> dict[str, Any]:
    """Code-first gap check against PlanIR + slots."""
    s = normalize_slots(slots)
    plan_n = normalize_plan_ir(plan, s)
    ops = [st.op for st in plan_n.steps]
    missing: list[str] = []

    if not plan_n.steps:
        missing.append("大纲无步骤")

    sendish = (
        any(k in (intent or "") for k in ("发", "发送", "消息"))
        or "send_message" in (intent or "")
        or bool(s.get("contact") or s.get("message"))
    )
    if sendish:
        if not s.get("message") and "type" not in ops:
            missing.append("缺少消息内容或输入步骤")
        if not s.get("window_title") and "activate" not in ops:
            missing.append("缺少应用窗口")
        if not s.get("contact") and "ocr_click" not in ops and "send_im" not in ops:
            missing.append("缺少联系人定位步骤")

    return {
        "complete": not missing,
        "missing": missing,
        "hints": missing,
    }


def infer_missing_slots(
    intent_tag: str,
    slots: dict[str, str],
    *,
    utterance: str = "",
) -> list[str]:
    """Suggest missing slot ids for clarify (no fake confirms)."""
    s = normalize_slots(slots)
    missing: list[str] = []
    tag = (intent_tag or "other").strip()
    text = utterance or ""
    if tag == "send_message" or any(k in text for k in ("发送", "发消息", "发给")):
        if not s.get("contact"):
            missing.append("contact")
        if not s.get("message"):
            missing.append("message")
    if tag == "window" and not s.get("window_title"):
        missing.append("window_title")
    if tag == "click_text" and not s.get("match_text") and not s.get("contact"):
        missing.append("match_text")
    if tag == "schedule" and not s.get("run_at"):
        missing.append("run_at")
    if tag == "find_image" and not s.get("image_ref"):
        missing.append("image_ref")
    return missing
