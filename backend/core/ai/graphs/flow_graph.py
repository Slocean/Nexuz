"""LangGraph step-wise Agent: understand → clarify → outline → gap → build → validate → summarize."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from backend.core.ai.checkpointer import get_checkpointer, thread_config
from backend.core.ai.draft_builder import draft_summary, empty_draft
from backend.core.ai.graphs.outline_build import build_draft_from_outline
from backend.core.ai.graphs.state import (
    FlowGraphState,
    build_draft_context,
    collect_coord_warnings,
    safe_json,
)
from backend.core.ai.graphs.streaming import emit_delta, emit_process, stream_chat_model
from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.lc.prompts import (
    BUILD_SYSTEM,
    GAP_SYSTEM,
    OUTLINE_SYSTEM,
    REPAIR_SYSTEM,
    SUMMARIZE_SYSTEM,
    UNDERSTAND_SYSTEM,
)
from backend.core.ai.lc.structured import (
    GapCheckResult,
    IntentUnderstanding,
    PlanOutline,
)
from backend.core.ai.lc.tools import ToolSession, build_orchestration_tools
from backend.core.ai.types import AiConfig

ProgressFn = Callable[[dict[str, Any]], None]
ValidateFn = Callable[[dict[str, Any]], str | None]


def _append_process(state: FlowGraphState, step: dict[str, Any]) -> list[dict[str, Any]]:
    proc = list(state.get("process") or [])
    proc.append(step)
    return proc


def _looks_like_fake_confirm(text: str) -> bool:
    t = text or ""
    return any(
        m in t
        for m in (
            "需确认",
            "请确认",
            "是否需要",
            "要不要",
            "是否移除",
            "是否添加",
            "是否符合您的预期",
        )
    )


def _deterministic_flow_reply(
    draft: dict[str, Any],
    summary: dict[str, Any],
    warnings: list[str],
    clarify: list[dict[str, Any]],
    *,
    intent: str = "",
    outline: dict[str, Any] | None = None,
) -> str:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    types: list[str] = []
    seen: set[str] = set()
    cur = draft.get("entry")
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        n = nodes[cur]
        if isinstance(n, dict):
            types.append(str(n.get("type") or ""))
            cur = n.get("next")
        else:
            break
    type_line = " → ".join(types) if types else "（空）"
    ncount = int(summary.get("node_count") or len(nodes) or 0)
    osteps = len((outline or {}).get("steps") or []) if isinstance(outline, dict) else 0
    if clarify:
        q = clarify[0].get("prompt") if isinstance(clarify[0], dict) else str(clarify[0])
        return (
            f"理解意图：{intent or '（待明确）'}\n"
            f"还不能落图（草稿 {ncount} 节点）。\n"
            f"需要你补充：{q}\n"
            "请直接回答后继续编排。"
        )
    if ncount <= 0:
        extra = f"\n原因：{warnings[0]}" if warnings else ""
        return (
            f"本轮没有生成任何节点，草稿为空。{extra}\n"
            f"大纲步数：{osteps}。请补充信息或换种说法后再试。"
        )
    warn = f"\n注意：{warnings[0]}" if warnings else ""
    return (
        f"意图：{intent or '已编排'}\n"
        f"草稿 {ncount} 个节点：{type_line}。"
        f"{warn}\n"
        "可在下方草稿卡片预览后点「应用到画布」。"
    )


def _merge_slots(base: dict[str, str], answers: dict[str, Any]) -> dict[str, str]:
    out = {str(k): str(v) for k, v in (base or {}).items() if v is not None}
    for k, v in (answers or {}).items():
        if v is None:
            continue
        out[str(k)] = str(v).strip()
    return out


def _ambiguities_to_questions(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in items or []:
        if hasattr(q, "model_dump"):
            d = q.model_dump()
        elif isinstance(q, dict):
            d = q
        else:
            continue
        prompt = str(d.get("prompt") or "").strip()
        if not prompt:
            continue
        # Drop fake-confirm style
        if _looks_like_fake_confirm(prompt):
            continue
        out.append(
            {
                "id": str(d.get("id") or f"q{len(out)+1}"),
                "prompt": prompt,
                "choices": list(d.get("choices") or []),
                "allow_free_text": bool(d.get("allow_free_text", True)),
            }
        )
    return out


def _run_tool_loop(
    *,
    llm: Any,
    tools: list[Any],
    system: str,
    user_blob: str,
    session: ToolSession,
    on_progress: ProgressFn | None,
    conversation_id: str,
    assistant_id: str,
    proc: list[dict[str, Any]],
    max_iters: int = 10,
) -> list[dict[str, Any]]:
    """Simple bind_tools loop; mutates session.draft in place."""
    tool_map = {t.name: t for t in tools}
    try:
        bound = llm.bind_tools(tools)
    except Exception:
        return proc
    messages: list[Any] = [
        SystemMessage(content=system),
        HumanMessage(content=user_blob),
    ]
    for _ in range(max_iters):
        try:
            ai = bound.invoke(messages)
        except Exception as exc:
            proc.append(
                {"kind": "warn", "node": "build_loop", "label": "工具循环", "text": str(exc)}
            )
            break
        if not isinstance(ai, AIMessage):
            break
        messages.append(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            break
        for call in calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            tid = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
            tool = tool_map.get(str(name))
            if tool is None:
                result = json.dumps({"ok": False, "error": f"未知工具 {name}"})
            else:
                try:
                    result = tool.invoke(args or {})
                except Exception as exc:
                    result = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            proc.append(
                {
                    "kind": "tool",
                    "node": "build_loop",
                    "label": str(name),
                    "name": str(name),
                    "text": str(result)[:240],
                    "ok": '"ok": false' not in str(result).lower(),
                }
            )
            if on_progress:
                on_progress(
                    {
                        "type": "process",
                        "mode": "flow",
                        "conversation_id": conversation_id,
                        "assistant_id": assistant_id,
                        "step": proc[-1],
                        "process": proc,
                        "node": "build_loop",
                    }
                )
            messages.append(
                ToolMessage(content=str(result)[:4000], tool_call_id=str(tid or name))
            )
    return proc


def make_flow_nodes(
    *,
    cfg: AiConfig | None,
    capture_fn: Callable[..., dict[str, Any]] | None,
    validate_fn: ValidateFn | None,
    on_progress: ProgressFn | None,
    conversation_id: str,
    assistant_id: str,
):
    def load_context(state: FlowGraphState) -> dict[str, Any]:
        draft = state.get("draft") or empty_draft()
        artifacts = state.get("artifacts") or {"shots": {}, "points": {}}
        slots = dict(state.get("known_slots") or {})
        # Merge prior clarify answers into slots
        slots = _merge_slots(slots, state.get("clarify_answers") or {})
        ctx = build_draft_context(
            draft,
            artifacts,
            allow_dangerous=bool(state.get("allow_dangerous")),
            slots=slots,
            intent=str(state.get("intent") or ""),
        )
        step = {
            "kind": "node",
            "node": "load_context",
            "label": "加载上下文",
            "text": f"节点 {draft_summary(draft).get('node_count', 0)} 个",
        }
        emit_process(
            on_progress,
            list(state.get("process") or []),
            step,
            mode="flow",
            conversation_id=conversation_id,
            assistant_id=assistant_id,
        )
        return {
            "context": ctx,
            "known_slots": slots,
            "process": _append_process(state, step),
            "gap_rounds": int(state.get("gap_rounds") or 0),
            "max_gap_rounds": int(state.get("max_gap_rounds") or 2),
            "repair_rounds": int(state.get("repair_rounds") or 0),
            "max_repair_rounds": int(state.get("max_repair_rounds") or 2),
            "strict_coords": True
            if state.get("strict_coords") is None
            else bool(state.get("strict_coords")),
            "validation_errors": [],
            "warnings": [],
            "status_hint": "",
            "clarify_questions": [],
        }

    def understand(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "understand",
            "label": "理解意图",
            "text": "分析话术…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        user_input = state.get("input") or ""
        prior_slots = dict(state.get("known_slots") or {})
        answers = dict(state.get("clarify_answers") or {})
        understanding: IntentUnderstanding
        try:
            llm = create_chat_model(cfg, temperature=0.1, streaming=False)
            structured = llm.with_structured_output(IntentUnderstanding)
            understanding = structured.invoke(
                [
                    SystemMessage(content=UNDERSTAND_SYSTEM),
                    SystemMessage(
                        content=(
                            f"已有槽位：{safe_json(prior_slots)}\n"
                            f"用户刚补充的答案：{safe_json(answers)}\n"
                            f"上下文：\n{state.get('context') or ''}"
                        )
                    ),
                    HumanMessage(content=user_input),
                ]
            )
            if not isinstance(understanding, IntentUnderstanding):
                understanding = IntentUnderstanding.model_validate(understanding)
        except Exception as exc:
            # Minimal offline understanding — extract nothing invented
            understanding = IntentUnderstanding(
                intent=user_input[:120],
                known_slots=prior_slots,
                ambiguities=[],
            )
            proc.append(
                {
                    "kind": "warn",
                    "node": "understand",
                    "label": "理解回退",
                    "text": f"结构化理解失败，使用弱回退：{exc}",
                }
            )
        slots = _merge_slots(understanding.known_slots, answers)
        slots = _merge_slots(prior_slots, slots)
        ambiguities = _ambiguities_to_questions(understanding.ambiguities)
        # If user just answered, drop resolved ambiguity ids
        if answers:
            answered = set(answers.keys())
            ambiguities = [q for q in ambiguities if q.get("id") not in answered]
            # Free-text answer to first pending: treat whole message as value for first unanswered
            if not ambiguities and answers.get("__free_text__"):
                pass
        proc = _append_process({**state, "process": proc}, step)
        proc.append(
            {
                "kind": "think",
                "label": "意图",
                "text": understanding.intent or user_input[:80],
            }
        )
        return {
            "intent": understanding.intent or user_input[:120],
            "known_slots": slots,
            "clarify_questions": ambiguities,
            "process": proc,
        }

    def clarify(state: FlowGraphState) -> dict[str, Any]:
        pending = list(state.get("clarify_questions") or [])
        answers = dict(state.get("clarify_answers") or {})
        step = {
            "kind": "node",
            "node": "clarify",
            "label": "澄清",
            "text": pending[0]["prompt"] if pending else "无歧义",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        # Only treat this user turn as an answer when resuming a prior clarify interrupt
        user_input = (state.get("input") or "").strip()
        resume = bool(state.get("resume_clarify"))
        if pending and user_input and resume:
            qid = str(pending[0].get("id") or "q1")
            if qid not in answers or not str(answers.get(qid) or "").strip():
                answers[qid] = user_input
                for ch in pending[0].get("choices") or []:
                    if str(ch) in user_input or user_input == str(ch):
                        answers[qid] = str(ch)
                        break
        slots = _merge_slots(state.get("known_slots") or {}, answers)
        still = []
        for q in pending:
            qid = str(q.get("id") or "")
            if qid and qid in answers and str(answers[qid]).strip():
                continue
            still.append(q)
        proc = _append_process({**state, "process": proc}, step)
        if still:
            proc.append(
                {
                    "kind": "clarify",
                    "node": "clarify",
                    "label": "需要你确认",
                    "text": still[0].get("prompt") or "请补充信息",
                }
            )
            return {
                "clarify_questions": still,
                "clarify_answers": answers,
                "known_slots": slots,
                "status_hint": "needs_clarify",
                "process": proc,
            }
        return {
            "clarify_questions": [],
            "clarify_answers": answers,
            "known_slots": slots,
            "status_hint": "",
            "process": proc,
        }

    def plan_outline(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "plan_outline",
            "label": "规划大纲",
            "text": "分步思路…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        intent = state.get("intent") or ""
        slots = dict(state.get("known_slots") or {})
        hints = list(state.get("gap_hints") or [])
        outline_prev = state.get("outline") if isinstance(state.get("outline"), dict) else {}
        try:
            llm = create_chat_model(cfg, temperature=0.2, streaming=False)
            structured = llm.with_structured_output(PlanOutline)
            result = structured.invoke(
                [
                    SystemMessage(content=OUTLINE_SYSTEM),
                    SystemMessage(
                        content=(
                            f"意图：{intent}\n槽位：{safe_json(slots)}\n"
                            f"补洞提示：{safe_json(hints)}\n"
                            f"上一版大纲：{safe_json(outline_prev)[:2000]}\n"
                            f"上下文：\n{state.get('context') or ''}"
                        )
                    ),
                    HumanMessage(content=state.get("input") or intent),
                ]
            )
            outline = result.model_dump() if isinstance(result, PlanOutline) else PlanOutline.model_validate(result).model_dump()
        except Exception as exc:
            outline = _fallback_outline(intent, slots)
            proc.append(
                {
                    "kind": "warn",
                    "node": "plan_outline",
                    "label": "大纲回退",
                    "text": str(exc),
                }
            )
        # Strip schedule if user said once
        t = state.get("input") or ""
        if any(k in t for k in ("执行一次", "马上", "立刻", "立即")) or str(
            slots.get("schedule") or ""
        ).lower() in ("false", "0", "no"):
            outline["steps"] = [
                s
                for s in (outline.get("steps") or [])
                if str((s or {}).get("block_hint") or "")
                not in ("schedule_trigger", "schedule_at", "schedule")
            ]
        proc = _append_process({**state, "process": proc}, step)
        proc.append(
            {
                "kind": "think",
                "label": "大纲",
                "text": f"{len(outline.get('steps') or [])} 步：{outline.get('summary') or ''}",
            }
        )
        return {"outline": outline, "process": proc}

    def gap_check(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "gap_check",
            "label": "查漏补缺",
            "text": "检查大纲…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        rounds = int(state.get("gap_rounds") or 0)
        outline = state.get("outline") if isinstance(state.get("outline"), dict) else {}
        slots = dict(state.get("known_slots") or {})
        intent = state.get("intent") or ""
        try:
            llm = create_chat_model(cfg, temperature=0, streaming=False)
            structured = llm.with_structured_output(GapCheckResult)
            result = structured.invoke(
                [
                    SystemMessage(content=GAP_SYSTEM),
                    HumanMessage(
                        content=(
                            f"意图：{intent}\n槽位：{safe_json(slots)}\n"
                            f"大纲：{safe_json(outline)}"
                        )
                    ),
                ]
            )
            gap = result.model_dump() if isinstance(result, GapCheckResult) else GapCheckResult.model_validate(result).model_dump()
        except Exception:
            gap = _fallback_gap(intent, slots, outline)
        complete = bool(gap.get("complete"))
        # Soft local checks
        steps = outline.get("steps") or []
        if not steps:
            complete = False
            gap.setdefault("missing", []).append("大纲为空")
        proc = _append_process({**state, "process": proc}, step)
        proc.append(
            {
                "kind": "think",
                "label": "查漏",
                "text": "通过" if complete else f"缺：{', '.join(gap.get('missing') or [])}",
            }
        )
        return {
            "process": proc,
            "gap_rounds": rounds + (0 if complete else 1),
            "status_hint": "outline_ok" if complete else "outline_gap",
            "gap_hints": list(gap.get("hints") or gap.get("missing") or []),
            "warnings": list(state.get("warnings") or [])
            + ([] if complete else list(gap.get("missing") or [])[:3]),
        }

    def build_loop(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "build_loop",
            "label": "逐步落图",
            "text": "调用工具添加节点…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        draft = copy.deepcopy(state.get("draft") or empty_draft())
        artifacts = copy.deepcopy(
            state.get("artifacts") or {"shots": {}, "points": {}}
        )
        trace = list(state.get("tool_trace") or [])
        outline = state.get("outline") if isinstance(state.get("outline"), dict) else {}
        slots = dict(state.get("known_slots") or {})
        session = ToolSession(
            draft=draft,
            artifacts=artifacts,
            tool_trace=trace,
            capture_fn=capture_fn,
            allow_dangerous=bool(state.get("allow_dangerous")),
            strict_coords=bool(state.get("strict_coords", True)),
        )
        tools = build_orchestration_tools(session, cfg=cfg)
        used_tools = False
        try:
            llm = create_chat_model(cfg, temperature=0.1, streaming=False)
            before = len(session.draft.get("nodes") or {})
            proc = _run_tool_loop(
                llm=llm,
                tools=tools,
                system=BUILD_SYSTEM,
                user_blob=(
                    f"意图：{state.get('intent')}\n槽位：{safe_json(slots)}\n"
                    f"大纲：{safe_json(outline)}\n"
                    f"当前草稿：\n{state.get('context') or ''}\n"
                    "请按大纲逐步用工具落图。"
                ),
                session=session,
                on_progress=on_progress,
                conversation_id=conversation_id,
                assistant_id=assistant_id,
                proc=proc,
            )
            after = len(session.draft.get("nodes") or {})
            used_tools = after > before or any(
                p.get("kind") == "tool" for p in proc[-20:]
            )
        except Exception as exc:
            proc.append(
                {"kind": "warn", "node": "build_loop", "label": "工具失败", "text": str(exc)}
            )

        # Fallback: deterministic outline expansion if tools produced nothing
        if not (session.draft.get("nodes") or {}):
            applied = build_draft_from_outline(
                session.draft,
                outline,
                slots=slots,
                artifacts=session.artifacts,
                tool_trace=session.tool_trace,
                strict_coords=bool(state.get("strict_coords", True)),
            )
            session.draft = applied["draft"]
            session.artifacts = applied["artifacts"]
            for err in applied.get("errors") or []:
                proc.append(
                    {"kind": "warn", "node": "build_loop", "label": "大纲落图", "text": err}
                )
            proc.append(
                {
                    "kind": "think",
                    "label": "落图",
                    "text": "工具无产出，已用大纲确定性展开"
                    if not used_tools
                    else "补全大纲展开",
                }
            )

        proc = _append_process({**state, "process": proc}, step)
        warnings = collect_coord_warnings(session.draft)
        return {
            "draft": session.draft,
            "artifacts": session.artifacts,
            "tool_trace": session.tool_trace,
            "process": proc,
            "warnings": warnings,
            "needs_locate": False,
            "locate_texts": [],
        }

    def validate(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "validate",
            "label": "校验草稿",
            "text": "检查入口与坐标…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        draft = state.get("draft") or empty_draft()
        errors: list[str] = []
        nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
        if nodes and not draft.get("entry"):
            errors.append("缺少入口节点 entry")
        if validate_fn is not None and nodes:
            try:
                msg = validate_fn(draft)
                if msg:
                    errors.append(str(msg))
            except Exception as exc:
                errors.append(f"validate_fn: {exc}")
        # Bound clicks check
        for nid, node in nodes.items():
            if not isinstance(node, dict) or node.get("type") != "click":
                continue
            params = node.get("params") if isinstance(node.get("params"), dict) else {}
            x, y = params.get("x"), params.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if not node.get("_ai_point_ref"):
                    errors.append(f"节点 {nid} 疑似裸坐标 click")
        proc = _append_process({**state, "process": proc}, step)
        return {"validation_errors": errors, "process": proc}

    def repair(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "repair",
            "label": "修复",
            "text": "根据校验错误修补…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        rounds = int(state.get("repair_rounds") or 0) + 1
        draft = copy.deepcopy(state.get("draft") or empty_draft())
        artifacts = copy.deepcopy(
            state.get("artifacts") or {"shots": {}, "points": {}}
        )
        session = ToolSession(
            draft=draft,
            artifacts=artifacts,
            tool_trace=list(state.get("tool_trace") or []),
            capture_fn=capture_fn,
            allow_dangerous=bool(state.get("allow_dangerous")),
            strict_coords=bool(state.get("strict_coords", True)),
        )
        tools = build_orchestration_tools(session, cfg=cfg)
        try:
            llm = create_chat_model(cfg, temperature=0, streaming=False)
            proc = _run_tool_loop(
                llm=llm,
                tools=tools,
                system=REPAIR_SYSTEM,
                user_blob=(
                    f"校验错误：{safe_json(state.get('validation_errors'))}\n"
                    f"大纲：{safe_json(state.get('outline'))}\n"
                    "请最小修补。"
                ),
                session=session,
                on_progress=on_progress,
                conversation_id=conversation_id,
                assistant_id=assistant_id,
                proc=proc,
                max_iters=6,
            )
        except Exception as exc:
            proc.append({"kind": "warn", "node": "repair", "label": "修复失败", "text": str(exc)})
        # Ensure entry if single chain
        nodes = session.draft.get("nodes") if isinstance(session.draft.get("nodes"), dict) else {}
        if nodes and not session.draft.get("entry"):
            session.draft["entry"] = next(iter(nodes.keys()))
        proc = _append_process({**state, "process": proc}, step)
        return {
            "draft": session.draft,
            "artifacts": session.artifacts,
            "tool_trace": session.tool_trace,
            "repair_rounds": rounds,
            "validation_errors": [],
            "process": proc,
        }

    def summarize(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "summarize",
            "label": "总结",
            "text": "生成回复…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        draft = state.get("draft") or empty_draft()
        summary = draft_summary(draft)
        warnings = list(state.get("warnings") or [])
        clarify = list(state.get("clarify_questions") or [])
        reply = _deterministic_flow_reply(
            draft,
            summary,
            warnings,
            clarify,
            intent=str(state.get("intent") or ""),
            outline=state.get("outline") if isinstance(state.get("outline"), dict) else None,
        )
        emit_delta(
            on_progress,
            mode="flow",
            conversation_id=conversation_id,
            assistant_id=assistant_id,
            text=reply,
            replace=True,
        )
        ncount = int(summary.get("node_count") or 0)
        if not clarify and ncount > 0:
            try:
                llm = create_chat_model(cfg, temperature=0, streaming=True)
                content, _ = stream_chat_model(
                    llm,
                    [
                        SystemMessage(content=SUMMARIZE_SYSTEM),
                        SystemMessage(content=f"事实摘要（勿违背）：\n{reply}"),
                        HumanMessage(content=f"用户原话：{state.get('input') or ''}"),
                    ],
                    on_progress=on_progress,
                    mode="flow",
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                )
                polished = (content or "").strip()
                if polished and not _looks_like_fake_confirm(polished) and "草稿为空" not in polished:
                    if str(ncount) in polished or "节点" in polished:
                        reply = polished
                        emit_delta(
                            on_progress,
                            mode="flow",
                            conversation_id=conversation_id,
                            assistant_id=assistant_id,
                            text=reply,
                            replace=True,
                        )
            except Exception:
                pass
        proc = _append_process({**state, "process": proc}, step)
        return {"reply": reply, "process": proc}

    return {
        "load_context": load_context,
        "understand": understand,
        "clarify": clarify,
        "plan_outline": plan_outline,
        "gap_check": gap_check,
        "build_loop": build_loop,
        "validate": validate,
        "repair": repair,
        "summarize": summarize,
    }


def _fallback_outline(intent: str, slots: dict[str, str]) -> dict[str, Any]:
    """Weak offline outline from slots only — no invented contacts."""
    steps: list[dict[str, Any]] = []
    i = 1
    if slots.get("run_at") or str(slots.get("schedule") or "").lower() in ("true", "1", "yes"):
        steps.append(
            {
                "id": f"s{i}",
                "goal": "定时触发",
                "block_hint": "schedule_trigger",
                "needs_sense": "none",
                "params": {"run_at": slots.get("run_at") or ""},
            }
        )
        i += 1
    if slots.get("window_title"):
        steps.append(
            {
                "id": f"s{i}",
                "goal": f"激活窗口 {slots['window_title']}",
                "block_hint": "window_activate",
                "needs_sense": "none",
                "params": {"title": slots["window_title"]},
            }
        )
        i += 1
    if slots.get("contact"):
        steps.append(
            {
                "id": f"s{i}",
                "goal": f"定位联系人 {slots['contact']}",
                "block_hint": "ocr_click",
                "needs_sense": "ocr",
                "match_text": slots["contact"],
            }
        )
        i += 1
    if slots.get("message"):
        steps.append(
            {
                "id": f"s{i}",
                "goal": "输入消息",
                "block_hint": "type_text",
                "needs_sense": "none",
                "params": {"text": slots["message"]},
            }
        )
        i += 1
        steps.append(
            {
                "id": f"s{i}",
                "goal": "点击发送",
                "block_hint": "ocr_click",
                "needs_sense": "ocr",
                "match_text": "发送",
            }
        )
        i += 1
    if not steps:
        import re

        typed = slots.get("message") or ""
        if not typed:
            m = re.search(
                r"(?:输入|键入|打字)\s*[「\"'『]?([^」\"'』\n]{1,80})",
                intent or "",
            )
            if m:
                typed = m.group(1).strip()
        if typed:
            steps.append(
                {
                    "id": "s1",
                    "goal": "短暂等待",
                    "block_hint": "delay",
                    "needs_sense": "none",
                    "params": {"ms": 500},
                }
            )
            steps.append(
                {
                    "id": "s2",
                    "goal": f"输入 {typed}",
                    "block_hint": "type_text",
                    "needs_sense": "none",
                    "params": {"text": typed},
                }
            )
        else:
            steps.append(
                {
                    "id": "s1",
                    "goal": "占位延时",
                    "block_hint": "delay",
                    "needs_sense": "none",
                    "params": {"ms": 500},
                }
            )
    return {"summary": intent[:80], "steps": steps}


def _fallback_gap(
    intent: str, slots: dict[str, str], outline: dict[str, Any]
) -> dict[str, Any]:
    missing: list[str] = []
    steps = outline.get("steps") or []
    hints_join = " ".join(
        str((s or {}).get("block_hint") or "") for s in steps if isinstance(s, dict)
    )
    # Send-message style intents
    if any(k in (intent or "") for k in ("发", "发送", "消息")):
        if not slots.get("message") and "type_text" not in hints_join:
            missing.append("缺少消息内容或输入步骤")
        if not slots.get("window_title") and "window_activate" not in hints_join:
            missing.append("缺少应用窗口")
        if not slots.get("contact") and "ocr_click" not in hints_join:
            missing.append("缺少联系人定位步骤")
    if not steps:
        missing.append("大纲无步骤")
    return {
        "complete": not missing,
        "missing": missing,
        "hints": missing,
    }


def _route_after_load(state: FlowGraphState) -> Literal["understand", "clarify"]:
    if state.get("resume_clarify") and state.get("clarify_questions"):
        return "clarify"
    return "understand"


def _route_after_understand(state: FlowGraphState) -> Literal["clarify", "plan_outline"]:
    if state.get("clarify_questions"):
        return "clarify"
    return "plan_outline"


def _route_after_clarify(state: FlowGraphState) -> Literal["summarize", "plan_outline"]:
    if state.get("status_hint") == "needs_clarify" or state.get("clarify_questions"):
        return "summarize"
    return "plan_outline"


def _route_after_gap(state: FlowGraphState) -> Literal["plan_outline", "build_loop"]:
    if state.get("status_hint") == "outline_gap":
        rounds = int(state.get("gap_rounds") or 0)
        max_r = int(state.get("max_gap_rounds") or 2)
        if rounds < max_r:
            return "plan_outline"
    return "build_loop"


def _route_after_validate(state: FlowGraphState) -> Literal["repair", "summarize"]:
    errors = state.get("validation_errors") or []
    if not errors:
        return "summarize"
    rounds = int(state.get("repair_rounds") or 0)
    max_r = int(state.get("max_repair_rounds") or 2)
    if rounds < max_r:
        return "repair"
    return "summarize"


def build_flow_graph(
    *,
    cfg: AiConfig | None = None,
    capture_fn: Callable[..., dict[str, Any]] | None = None,
    validate_fn: ValidateFn | None = None,
    on_progress: ProgressFn | None = None,
    conversation_id: str = "",
    assistant_id: str = "",
    checkpointer: Any | None = None,
):
    nodes = make_flow_nodes(
        cfg=cfg,
        capture_fn=capture_fn,
        validate_fn=validate_fn,
        on_progress=on_progress,
        conversation_id=conversation_id,
        assistant_id=assistant_id,
    )
    g = StateGraph(FlowGraphState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_conditional_edges(
        "load_context",
        _route_after_load,
        {"understand": "understand", "clarify": "clarify"},
    )
    g.add_conditional_edges(
        "understand",
        _route_after_understand,
        {"clarify": "clarify", "plan_outline": "plan_outline"},
    )
    g.add_conditional_edges(
        "clarify",
        _route_after_clarify,
        {"summarize": "summarize", "plan_outline": "plan_outline"},
    )
    g.add_edge("plan_outline", "gap_check")
    g.add_conditional_edges(
        "gap_check",
        _route_after_gap,
        {"plan_outline": "plan_outline", "build_loop": "build_loop"},
    )
    g.add_edge("build_loop", "validate")
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"repair": "repair", "summarize": "summarize"},
    )
    g.add_edge("repair", "validate")
    g.add_edge("summarize", END)
    return g.compile(checkpointer=checkpointer)


def run_flow_graph(
    *,
    conversation_id: str,
    user_text: str,
    draft: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
    base_flow: dict[str, Any] | None = None,
    cfg: AiConfig | None = None,
    capture_fn: Callable[..., dict[str, Any]] | None = None,
    validate_fn: ValidateFn | None = None,
    on_progress: ProgressFn | None = None,
    assistant_id: str = "",
    allow_dangerous: bool = False,
    use_checkpoint: bool = True,
    clarify_answers: dict[str, Any] | None = None,
    known_slots: dict[str, str] | None = None,
    intent: str = "",
    outline: dict[str, Any] | None = None,
    resume_clarify: bool = False,
    pending_clarify: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invoke the step-wise flow graph once and return final state fields."""
    cp = None
    if use_checkpoint:
        try:
            cp = get_checkpointer()
        except Exception:
            cp = None
    graph = build_flow_graph(
        cfg=cfg,
        capture_fn=capture_fn,
        validate_fn=validate_fn,
        on_progress=on_progress,
        conversation_id=conversation_id,
        assistant_id=assistant_id,
        checkpointer=cp,
    )
    init: FlowGraphState = {
        "input": user_text,
        "draft": draft,
        "base_flow": base_flow,
        "artifacts": artifacts or {"shots": {}, "points": {}},
        "tool_trace": [],
        "process": [],
        "repair_rounds": 0,
        "gap_rounds": 0,
        "max_repair_rounds": 2,
        "max_gap_rounds": 2,
        "allow_dangerous": allow_dangerous,
        "strict_coords": True,
        "clarify_answers": dict(clarify_answers or {}),
        "known_slots": dict(known_slots or {}),
        "intent": intent or "",
        "outline": outline or {},
        "clarify_questions": list(pending_clarify or []),
        "resume_clarify": bool(resume_clarify),
        "gap_hints": [],
        "status_hint": "",
    }
    config = thread_config(conversation_id) if cp is not None else None
    final = graph.invoke(init, config=config) if config else graph.invoke(init)
    return {
        "ok": True,
        "draft": final.get("draft") or draft,
        "artifacts": final.get("artifacts") or artifacts or {"shots": {}, "points": {}},
        "process": final.get("process") or [],
        "tool_trace": final.get("tool_trace") or [],
        "warnings": final.get("warnings") or [],
        "reply": final.get("reply") or "",
        "clarify_questions": final.get("clarify_questions") or [],
        "intent": final.get("intent") or "",
        "known_slots": final.get("known_slots") or {},
        "outline": final.get("outline") or {},
        "plan": {
            "intent_summary": final.get("intent") or "",
            "outline": final.get("outline") or {},
        },
        "status_hint": final.get("status_hint") or "",
        "validation_errors": final.get("validation_errors") or [],
    }
