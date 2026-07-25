"""LangGraph flow orchestration: plan → build → locate → validate → repair → summarize."""

from __future__ import annotations

import copy
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from backend.core.ai.checkpointer import get_checkpointer, thread_config
from backend.core.ai.draft_builder import draft_summary, empty_draft
from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text
from backend.core.ai.graphs.state import (
    FlowGraphState,
    build_draft_context,
    collect_coord_warnings,
    safe_json,
)
from backend.core.ai.graphs.streaming import emit_delta, emit_process, stream_chat_model
from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.lc.prompts import PLAN_SYSTEM, REPAIR_SYSTEM, SUMMARIZE_SYSTEM
from backend.core.ai.lc.structured import FlowSpec, flow_spec_to_dict, parse_flow_spec
from backend.core.ai.locate import capture_to_artifact, locate_text
from backend.core.ai.types import AiConfig

ProgressFn = Callable[[dict[str, Any]], None]
ValidateFn = Callable[[dict[str, Any]], str | None]


def _append_process(state: FlowGraphState, step: dict[str, Any]) -> list[dict[str, Any]]:
    proc = list(state.get("process") or [])
    proc.append(step)
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
    """Build node callables closed over runtime deps (progress, capture, validate)."""

    def load_context(state: FlowGraphState) -> dict[str, Any]:
        draft = state.get("draft") or empty_draft()
        artifacts = state.get("artifacts") or {"shots": {}, "points": {}}
        ctx = build_draft_context(
            draft,
            artifacts,
            allow_dangerous=bool(state.get("allow_dangerous")),
        )
        step = {
            "kind": "node",
            "node": "load_context",
            "label": "加载草稿上下文",
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
            "process": _append_process(state, step),
            "repair_rounds": int(state.get("repair_rounds") or 0),
            "max_repair_rounds": int(state.get("max_repair_rounds") or 2),
            "strict_coords": True
            if state.get("strict_coords") is None
            else bool(state.get("strict_coords")),
            "validation_errors": [],
            "warnings": [],
        }

    def planner(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "planner",
            "label": "规划 FlowSpec",
            "text": "结构化规划中…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        user_input = state.get("input") or ""
        context = state.get("context") or ""
        plan_dict: dict[str, Any]
        try:
            llm = create_chat_model(cfg, temperature=0.2, streaming=False)
            structured = llm.with_structured_output(FlowSpec)
            result = structured.invoke(
                [
                    SystemMessage(content=PLAN_SYSTEM),
                    SystemMessage(content=f"当前草稿与上下文：\n{context}"),
                    HumanMessage(content=user_input),
                ]
            )
            plan_dict = flow_spec_to_dict(result)
        except Exception as exc:
            # Fallback heuristic so offline / weak models still produce something
            plan = heuristic_plan_from_text(user_input)
            plan_dict = plan.model_dump()
            proc.append(step)
            proc.append(
                {
                    "kind": "warn",
                    "node": "planner",
                    "label": "规划回退",
                    "text": f"结构化规划失败，使用启发式：{exc}",
                }
            )
            return {
                "plan": plan_dict,
                "needs_locate": bool(plan_dict.get("needs_locate")),
                "locate_texts": list(plan_dict.get("locate_texts") or []),
                "process": proc,
            }

        proc.append(step)
        think = {
            "kind": "think",
            "label": "计划",
            "text": plan_dict.get("intent_summary")
            or f"{len(plan_dict.get('steps') or [])} 步",
        }
        proc.append(think)
        if on_progress:
            on_progress(
                {
                    "type": "process",
                    "mode": "flow",
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                    "step": think,
                    "process": proc,
                    "node": "planner",
                }
            )
        return {
            "plan": plan_dict,
            "needs_locate": bool(plan_dict.get("needs_locate")),
            "locate_texts": list(plan_dict.get("locate_texts") or []),
            "process": proc,
        }

    def builder(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "builder",
            "label": "配方落图",
            "text": "按 FlowSpec 写入草稿…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        plan = parse_flow_spec(state.get("plan"))
        # If planner asked clarifying questions and user has not answered yet, pause.
        pending = [
            {
                "id": q.id,
                "prompt": q.prompt,
                "choices": list(q.choices or []),
                "allow_free_text": bool(q.allow_free_text),
            }
            for q in (plan.clarify_questions or [])
        ]
        if pending and not state.get("clarify_answers"):
            proc = _append_process({**state, "process": proc}, step)
            proc.append(
                {
                    "kind": "clarify",
                    "node": "builder",
                    "label": "需要你确认",
                    "text": pending[0].get("prompt") or "请补充信息",
                }
            )
            return {
                "clarify_questions": pending,
                "status_hint": "needs_clarify",
                "process": proc,
                "needs_locate": bool(plan.needs_locate),
                "locate_texts": list(plan.locate_texts or []),
            }

        draft = copy.deepcopy(state.get("draft") or empty_draft())
        artifacts = copy.deepcopy(
            state.get("artifacts") or {"shots": {}, "points": {}}
        )
        trace = list(state.get("tool_trace") or [])
        applied = apply_flow_spec(
            draft,
            state.get("plan"),
            artifacts=artifacts,
            allow_dangerous=bool(state.get("allow_dangerous")),
            strict_coords=bool(state.get("strict_coords", True)),
            tool_trace=trace,
        )
        for err in applied.get("errors") or []:
            proc.append({"kind": "warn", "node": "builder", "label": "落图警告", "text": err})
        proc = _append_process({**state, "process": proc}, step)
        needs = bool(applied.get("needs_locate") or state.get("needs_locate") or plan.needs_locate)
        texts = list(applied.get("locate_texts") or state.get("locate_texts") or plan.locate_texts or [])
        return {
            "draft": applied["draft"],
            "artifacts": applied["artifacts"],
            "tool_trace": applied["tool_trace"],
            "needs_locate": needs,
            "locate_texts": texts,
            "process": proc,
            "warnings": collect_coord_warnings(applied["draft"]),
            "prefer_vision": bool(plan.prefer_vision),
        }

    def locator(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "locator",
            "label": "感知取点",
            "text": "截图 → 多模态/OCR 定位…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        artifacts = copy.deepcopy(
            state.get("artifacts") or {"shots": {}, "points": {}}
        )
        draft = state.get("draft") or empty_draft()
        plan = parse_flow_spec(state.get("plan"))
        texts = list(state.get("locate_texts") or [])
        if not texts:
            for s in plan.steps:
                if s.match_text:
                    texts.append(s.match_text)
                mt = (s.params or {}).get("match_text")
                if mt:
                    texts.append(str(mt))

        if capture_fn is not None:
            cap = capture_to_artifact(capture_fn, hide_window=True)
            if cap.get("ok"):
                art = cap["artifact"]
                artifacts.setdefault("shots", {})[art["shot_id"]] = art
                proc.append(
                    {
                        "kind": "tool",
                        "label": "截取屏幕",
                        "text": f"{art.get('width')}×{art.get('height')}",
                    }
                )

        from backend.core.ai.vision_locate import (
            infer_supports_vision,
            locate_on_screenshot_vision,
        )

        use_vision = bool(plan.prefer_vision)
        if cfg is not None:
            if cfg.supports_vision is not None:
                use_vision = use_vision or bool(cfg.supports_vision)
            else:
                use_vision = use_vision or infer_supports_vision(cfg.model)

        clarify: list[dict[str, Any]] = []
        for q in plan.clarify_questions or []:
            clarify.append(
                {
                    "id": q.id,
                    "prompt": q.prompt,
                    "choices": list(q.choices or []),
                    "allow_free_text": bool(q.allow_free_text),
                }
            )

        for text in texts:
            if not (text or "").strip():
                continue
            loc: dict[str, Any] = {"ok": False}
            if use_vision:
                loc = locate_on_screenshot_vision(
                    artifacts, query=str(text), cfg=cfg
                )
                proc.append(
                    {
                        "kind": "tool",
                        "label": "多模态看图定点",
                        "text": (
                            f"「{text}」→ ok={loc.get('ok')} "
                            f"ref={loc.get('point_ref')} "
                            f"{loc.get('error') or ''}"
                        ),
                    }
                )
            if not loc.get("ok"):
                loc = locate_text(
                    artifacts,
                    match_text=str(text),
                    match_mode="contains",
                    capture_fn=capture_fn,
                )
                proc.append(
                    {
                        "kind": "tool",
                        "label": "OCR 文字定位",
                        "text": (
                            f"「{text}」→ ok={loc.get('ok')} "
                            f"ref={loc.get('point_ref')}"
                        ),
                    }
                )
            if not loc.get("ok"):
                clarify.append(
                    {
                        "id": f"locate_{text}",
                        "prompt": f"未能自动定位「{text}」，请选择或手动取点",
                        "choices": [],
                        "allow_free_text": True,
                    }
                )

        proc = _append_process({**state, "process": proc}, step)
        out: dict[str, Any] = {
            "artifacts": artifacts,
            "draft": draft,
            "process": proc,
        }
        if clarify:
            out["clarify_questions"] = clarify
            out["status_hint"] = "needs_clarify"
        return out

    def validate(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "validate",
            "label": "校验草稿",
            "text": "运行 validate_flow…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        draft = state.get("draft") or empty_draft()
        errors: list[str] = []
        if not draft.get("entry") and (draft.get("nodes") or {}):
            errors.append("缺少 entry 入口节点")
        if validate_fn is not None:
            err = validate_fn(draft)
            if err:
                errors.append(err)
        # structural: nodes with unverified coords under strict mode are warnings
        warnings = collect_coord_warnings(draft)
        proc = _append_process({**state, "process": proc}, step)
        if errors:
            proc.append(
                {
                    "kind": "warn",
                    "node": "validate",
                    "label": "校验失败",
                    "text": "；".join(errors)[:300],
                }
            )
        return {
            "validation_errors": errors,
            "warnings": warnings,
            "process": proc,
        }

    def repair(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "repair",
            "label": "修复 FlowSpec",
            "text": "根据校验错误重规划…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        rounds = int(state.get("repair_rounds") or 0) + 1
        errors = state.get("validation_errors") or []
        context = state.get("context") or build_draft_context(
            state.get("draft"), state.get("artifacts")
        )
        plan_json = safe_json(state.get("plan"))
        try:
            llm = create_chat_model(cfg, temperature=0.2, streaming=False)
            structured = llm.with_structured_output(FlowSpec)
            result = structured.invoke(
                [
                    SystemMessage(content=REPAIR_SYSTEM),
                    SystemMessage(
                        content=(
                            f"当前上下文：\n{context}\n\n"
                            f"校验错误：\n{chr(10).join(errors)}\n\n"
                            f"当前 FlowSpec：\n{plan_json}"
                        )
                    ),
                    HumanMessage(content="请输出修复后的 FlowSpec。"),
                ]
            )
            plan_dict = flow_spec_to_dict(result)
        except Exception:
            plan_dict = flow_spec_to_dict(state.get("plan"))

        proc = _append_process({**state, "process": proc}, step)
        # Reset draft to base before re-applying repaired plan for cleaner rebuild
        base = state.get("base_flow")
        fresh = copy.deepcopy(base) if isinstance(base, dict) else empty_draft()
        return {
            "plan": plan_dict,
            "draft": fresh,
            "repair_rounds": rounds,
            "validation_errors": [],
            "process": proc,
            "needs_locate": bool(plan_dict.get("needs_locate")),
            "locate_texts": list(plan_dict.get("locate_texts") or []),
        }

    def summarize(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "summarize",
            "label": "总结编排",
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
        fallback = (
            f"已完成本轮编排，草稿现有 {summary.get('node_count', 0)} 个节点"
            + (f"（入口：{summary.get('entry')}）" if summary.get("entry") else "")
            + "。请查看草稿卡片，确认后点击「应用到画布」。"
        )
        reply = fallback
        try:
            llm = create_chat_model(cfg, temperature=0.3, streaming=True)
            emit_delta(
                on_progress,
                mode="flow",
                conversation_id=conversation_id,
                assistant_id=assistant_id,
                text="",
                replace=True,
            )
            content, _ = stream_chat_model(
                llm,
                [
                    SystemMessage(content=SUMMARIZE_SYSTEM),
                    SystemMessage(
                        content=(
                            f"草稿摘要：\n{safe_json(summary)}\n"
                            f"警告：\n{warnings or '无'}"
                        )
                    ),
                    HumanMessage(content=f"用户原话：{state.get('input') or ''}"),
                ],
                on_progress=on_progress,
                mode="flow",
                conversation_id=conversation_id,
                assistant_id=assistant_id,
            )
            if (content or "").strip():
                reply = content.strip()
            else:
                emit_delta(
                    on_progress,
                    mode="flow",
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    text=fallback,
                    replace=True,
                )
        except Exception:
            emit_delta(
                on_progress,
                mode="flow",
                conversation_id=conversation_id,
                assistant_id=assistant_id,
                text=fallback,
                replace=True,
            )
        proc = _append_process({**state, "process": proc}, step)
        return {"reply": reply, "process": proc}

    return {
        "load_context": load_context,
        "planner": planner,
        "builder": builder,
        "locator": locator,
        "validate": validate,
        "repair": repair,
        "summarize": summarize,
    }


def _route_after_build(state: FlowGraphState) -> Literal["locator", "validate", "summarize"]:
    if state.get("status_hint") == "needs_clarify" or state.get("clarify_questions"):
        return "summarize"
    if state.get("needs_locate") or state.get("locate_texts"):
        return "locator"
    return "validate"


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
    g.add_edge("load_context", "planner")
    g.add_edge("planner", "builder")
    g.add_conditional_edges(
        "builder",
        _route_after_build,
        {"locator": "locator", "validate": "validate", "summarize": "summarize"},
    )
    g.add_edge("locator", "validate")
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"repair": "repair", "summarize": "summarize"},
    )
    g.add_edge("repair", "builder")
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
) -> dict[str, Any]:
    """Invoke the flow graph once and return final state fields."""
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
        "max_repair_rounds": 2,
        "allow_dangerous": allow_dangerous,
        "strict_coords": True,
        "messages": [HumanMessage(content=user_text)],
    }
    config = thread_config(conversation_id) if cp is not None else None
    final = graph.invoke(init, config=config)
    return {
        "ok": True,
        "draft": final.get("draft") or draft,
        "artifacts": final.get("artifacts") or artifacts or {},
        "plan": final.get("plan") or {},
        "reply": final.get("reply") or "",
        "process": final.get("process") or [],
        "tool_trace": final.get("tool_trace") or [],
        "warnings": final.get("warnings") or [],
        "validation_errors": final.get("validation_errors") or [],
        "clarify_questions": final.get("clarify_questions") or [],
        "status_hint": final.get("status_hint") or "",
        "error": final.get("error"),
    }
