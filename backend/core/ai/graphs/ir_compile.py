"""Compile compact PlanIR → session draft via outline_build / recipes."""

from __future__ import annotations

from typing import Any

from backend.core.ai.draft_builder import set_entry
from backend.core.ai.graphs.agent_ir import (
    CANONICAL_SLOT_KEYS,
    PlanIR,
    format_ir_for_prompt,
    merge_and_normalize,
    normalize_plan_ir,
    plan_ir_to_outline,
)
from backend.core.ai.graphs.outline_build import build_draft_from_outline


def _resolve_arg_refs(args: dict[str, str], slots: dict[str, str]) -> dict[str, str]:
    """Replace values that are slot key names with slot values; never invent."""
    out: dict[str, str] = {}
    for k, v in (args or {}).items():
        val = str(v or "").strip()
        if val in CANONICAL_SLOT_KEYS and slots.get(val):
            out[k] = slots[val]
        elif val.startswith("$") and slots.get(val[1:]):
            out[k] = slots[val[1:]]
        else:
            out[k] = val
    return out


def _resolve_plan_args(plan: PlanIR, slots: dict[str, str]) -> PlanIR:
    steps = []
    for st in plan.steps:
        resolved = _resolve_arg_refs(dict(st.a or {}), slots)
        # Prefer slot window for ocr when not provided
        if st.op in ("ocr_click", "activate") and not resolved.get("window"):
            if slots.get("window_title"):
                resolved["window"] = slots["window_title"]
        if st.op == "type" and not resolved.get("text") and slots.get("message"):
            resolved["text"] = slots["message"]
        if st.op == "ocr_click" and not resolved.get("text"):
            if slots.get("match_text"):
                resolved["text"] = slots["match_text"]
            elif slots.get("contact"):
                resolved["text"] = slots["contact"]
        steps.append(st.model_copy(update={"a": resolved}))
    return PlanIR(steps=steps)


def compile_ir(
    plan: PlanIR | dict[str, Any] | None,
    slots: dict[str, str] | None,
    draft: dict[str, Any],
    *,
    artifacts: dict[str, Any] | None = None,
    tool_trace: list[dict[str, Any]] | None = None,
    strict_coords: bool = True,
    utterance: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """
    Expand PlanIR into draft nodes.

    Returns {ok, draft, artifacts, tool_trace, errors, plan_ir, outline}.
    Does not invent contact/window/message values missing from slots/args.
    """
    s = merge_and_normalize(slots, utterance=utterance)
    plan_n = normalize_plan_ir(plan, s)
    plan_n = _resolve_plan_args(plan_n, s)

    # Validate required args before compile (collect errors, skip inventing)
    pre_errors: list[str] = []
    for st in plan_n.steps:
        if st.op == "activate" and not (st.a.get("window") or s.get("window_title")):
            pre_errors.append("activate 缺少 window")
        if st.op == "ocr_click" and not st.a.get("text"):
            pre_errors.append("ocr_click 缺少 text")
        if st.op == "type" and not st.a.get("text"):
            pre_errors.append("type 缺少 text")
        if st.op == "find_image_click" and not st.a.get("image_ref"):
            pre_errors.append("find_image_click 缺少 image_ref")

    outline = plan_ir_to_outline(plan_n, summary=summary or "", slots=s)
    # Inject window_title into ocr outline params from slots
    for step in outline.get("steps") or []:
        if not isinstance(step, dict):
            continue
        params = step.setdefault("params", {})
        if isinstance(params, dict) and not params.get("window_title") and s.get("window_title"):
            params["window_title"] = s["window_title"]
        if step.get("block_hint") == "ocr_click" and not step.get("match_text"):
            # already validated above
            pass

    applied = build_draft_from_outline(
        draft,
        outline,
        slots=s,
        artifacts=artifacts,
        tool_trace=tool_trace,
        strict_coords=strict_coords,
    )
    errors = list(pre_errors) + list(applied.get("errors") or [])
    out_draft = applied["draft"]
    # Ensure entry
    nodes = out_draft.get("nodes") if isinstance(out_draft.get("nodes"), dict) else {}
    if nodes and not out_draft.get("entry"):
        # first node in outline order if possible
        first = next(iter(nodes.keys()), None)
        if first:
            out_draft = set_entry(out_draft, first)

    return {
        "ok": not errors and bool(nodes),
        "draft": out_draft,
        "artifacts": applied.get("artifacts") or {"shots": {}, "points": {}},
        "tool_trace": applied.get("tool_trace") or [],
        "errors": errors,
        "plan_ir": plan_n.model_dump(),
        "outline": outline,
        "ir_prompt": format_ir_for_prompt(plan_n),
    }
