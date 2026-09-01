"""LangGraph step-wise Agent: understand → clarify → outline → gap → build → validate → summarize."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from backend.core.ai.checkpointer import get_checkpointer, thread_config
from backend.core.ai.context_budget import (
    estimate_tokens,
    fit_prompt_blob,
    maybe_compact,
)
from backend.core.ai.draft_builder import draft_summary, empty_draft, set_entry
from backend.core.ai.graphs.agent_ir import (
    PlanIR,
    PlanIRDraft,
    UnderstandIR,
    build_task_contract,
    collect_unsupported_ir_ops,
    derive_goals_from_plan_ir,
    evaluate_task_coverage,
    format_ir_for_prompt,
    gap_from_ir,
    merge_and_normalize,
    missing_to_questions,
    normalize_plan_ir,
    parse_plan_ir,
    plan_ir_from_slots,
    plan_ir_looks_weak,
    plan_ir_to_dict,
    plan_ir_to_outline,
    reconcile_intent_tag,
    task_contract_to_dict,
    validate_plan_draft,
)
from backend.core.ai.graphs.ir_compile import compile_ir
from backend.core.ai.graphs.state import (
    FlowGraphState,
    build_draft_context,
    collect_coord_warnings,
    safe_json,
)
from backend.core.ai.graphs.streaming import emit_delta, emit_process, stream_chat_model
from backend.core.ai.lc.models import create_chat_model
from backend.core.ai.lc.prompts import (
    BUILD_STRUCTURED_SYSTEM,
    BUILD_SYSTEM,
    OUTLINE_SYSTEM,
    REPAIR_SYSTEM,
    SUMMARIZE_SYSTEM,
    UNDERSTAND_SYSTEM,
)
from backend.core.ai.lc.structured import ToolActionBatch
from backend.core.ai.lc.tools import ToolSession, build_orchestration_tools
from backend.core.ai.lc.structured_call import invoke_structured
from backend.core.ai.token_scheduler import (
    ContextLayer,
    MemoryRouter,
    compile_layers,
    distill_tool_result,
    guarded_structured_invoke,
    is_length_limit_error,
    plan_call,
)
from backend.core.ai.token_scheduler.output_planner import OutputProfile
from backend.core.ai.types import AiConfig

ProgressFn = Callable[[dict[str, Any]], None]
ValidateFn = Callable[[dict[str, Any]], str | None]


def _draft_shell_for_recompile(source: dict[str, Any] | None) -> dict[str, Any]:
    """Keep draft identity/vars but drop nodes so IR compile does not append."""
    src = source if isinstance(source, dict) else {}
    shell = empty_draft(name=str(src.get("name") or "AI 草稿"))
    if src.get("flow_id"):
        shell["flow_id"] = src["flow_id"]
    if isinstance(src.get("variables"), dict):
        shell["variables"] = copy.deepcopy(src["variables"])
    if isinstance(src.get("variable_schemas"), dict):
        shell["variable_schemas"] = copy.deepcopy(src["variable_schemas"])
    return shell

# After LM Studio / bad chat-template 400, skip bind_tools for the process lifetime.
_NATIVE_TOOLS_UNAVAILABLE = False


def _short_err(
    exc: BaseException | str,
    *,
    limit: int = 180,
    length_retried: bool = False,
) -> str:
    text = str(exc).replace("\n", " ").strip()
    if "jinja" in text.lower() or "prompt template" in text.lower():
        return "网关 tool 模板不可用（已切换旁路）"
    low = text.lower()
    if "invalid temperature" in low or "only 0.6 is allowed" in low:
        return "网关拒绝 temperature（已按模型固定值重试/请更新客户端）"
    retried = length_retried or bool(getattr(exc, "_nexuz_length_retried", False))
    if "length limit" in low or "max_tokens" in low:
        if retried:
            return "输出长度上限不足（max_tokens），抬额/续写后仍无法解析结构化结果"
        return "输出长度上限不足（max_tokens），未能解析结构化结果"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _structured_with_budget(
    cfg: AiConfig | None,
    purpose: OutputProfile | str,
    schema: type,
    messages: list[Any],
    *,
    compact_messages: list[Any] | None = None,
    temperature: float = 0.1,
) -> Any:
    """Dual-budget structured invoke (raise output once, then continue)."""
    return guarded_structured_invoke(
        cfg,
        purpose,
        schema,
        messages,
        compact_messages=compact_messages,
        temperature=temperature,
        # Pass module symbol so tests can monkeypatch flow_graph.create_chat_model
        create_model=create_chat_model,
    )


def _compile_user_blob(
    cfg: AiConfig | None,
    profile: OutputProfile | str,
    *,
    system: str,
    layers: list[ContextLayer],
    tool_overhead_tokens: int = 0,
) -> tuple[str, Any]:
    """Pack user-side layers into available_input; return (packed, CallBudget)."""
    budget = plan_call(
        cfg,
        profile,
        system_text=system,
        tool_overhead_tokens=tool_overhead_tokens,
    )
    packed = compile_layers(layers, budget.available_input)
    return packed, budget


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


def _collapse_stutter(text: str) -> str:
    """Collapse immediate repeated chunks in stuttered OCR/LLM text."""
    import re

    s = str(text or "").strip()
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(.{2,24}?)\1+", r"\1", s)
    return s


def _sanitize_clarify_choice(raw: Any) -> str | None:
    """Drop garbage / underscore-spam choices that break the clarify chip UI."""
    import re

    s = _collapse_stutter(str(raw or "").strip())
    if not s:
        return None
    if len(s) > 32:
        return None
    if s.count("_") >= 2 or re.search(r"_{2,}", s):
        return None
    if re.fullmatch(r"[\W_]+", s, flags=re.UNICODE):
        return None
    # Reject pseudo-tokens like file_to_text
    if re.fullmatch(r"[A-Za-z0-9_]+", s) and "_" in s:
        return None
    return s


def _ambiguities_to_questions(
    items: list[Any],
    *,
    known_slots: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    slots = {str(k): str(v).strip() for k, v in (known_slots or {}).items() if str(v).strip()}
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
        qid = str(d.get("id") or f"q{len(out)+1}")
        # Slot already filled → not a real ambiguity
        if qid in slots and slots[qid]:
            continue
        if slots.get("contact") and any(
            k in prompt for k in ("发给谁", "给谁", "哪位联系人", "联系人", "发送消息给谁")
        ):
            continue
        if slots.get("message") and any(
            k in prompt for k in ("发什么", "什么消息", "消息内容", "发送内容")
        ):
            continue
        if slots.get("window_title") and any(
            k in prompt for k in ("哪个应用", "哪个窗口", "什么软件")
        ):
            continue
        cleaned: list[str] = []
        seen: set[str] = set()
        for c in list(d.get("choices") or []):
            sc = _sanitize_clarify_choice(c)
            if not sc or sc in seen:
                continue
            seen.add(sc)
            cleaned.append(sc)
        out.append(
            {
                "id": qid,
                "prompt": prompt,
                "choices": cleaned,
                "allow_free_text": bool(d.get("allow_free_text", True)),
            }
        )
    return out


def _is_native_tools_broken(exc: BaseException) -> bool:
    """LM Studio / bad chat templates often 400 on OpenAI-style tools."""
    msg = str(exc).lower()
    needles = (
        "jinja",
        "prompt template",
        "undefinedvalue",
        "not a function",
        "does not support tools",
        "tools is not supported",
        "tool calling is not supported",
        "function calling",
        "tool_choice",
    )
    return any(n in msg for n in needles)


def _mark_native_tools_unavailable() -> None:
    global _NATIVE_TOOLS_UNAVAILABLE
    _NATIVE_TOOLS_UNAVAILABLE = True


def _emit_tool_step(
    *,
    proc: list[dict[str, Any]],
    name: str,
    result: str,
    on_progress: ProgressFn | None,
    conversation_id: str,
    assistant_id: str,
    node: str = "build_loop",
) -> None:
    proc.append(
        {
            "kind": "tool",
            "node": node,
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
                "node": node,
            }
        )


def _invoke_named_tool(tool_map: dict[str, Any], name: str, args: Any) -> str:
    tool = tool_map.get(str(name))
    if tool is None:
        return json.dumps({"ok": False, "error": f"未知工具 {name}"}, ensure_ascii=False)
    try:
        return str(tool.invoke(args or {}))
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def _run_structured_action_loop(
    *,
    llm: Any,
    tool_map: dict[str, Any],
    user_blob: str,
    session: ToolSession,
    on_progress: ProgressFn | None,
    conversation_id: str,
    assistant_id: str,
    proc: list[dict[str, Any]],
    max_iters: int = 10,
    node: str = "build_loop",
    cfg: AiConfig | None = None,
) -> list[dict[str, Any]]:
    """ReAct via structured ToolActionBatch — bypasses broken native tool templates."""
    proc.append(
        {
            "kind": "info",
            "node": node,
            "label": "结构化落图",
            "text": "JSON 动作协议逐步落图",
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
                "node": node,
            }
        )
    # Keep prompt small — long tool catalogs encourage local models to ramble past max_tokens.
    core_tools = [
        n
        for n in (
            "draft_add_node",
            "draft_connect",
            "draft_set_entry",
            "draft_update_node",
            "draft_get",
            "call_skill",
            "run_block",
            "done",
        )
        if n == "done" or n in tool_map
    ]
    tool_names = ", ".join(core_tools)
    last_results = "(无)"
    patch_budget = plan_call(cfg, "patch", system_text=BUILD_STRUCTURED_SYSTEM)
    in_budget = max(400, patch_budget.available_input)
    for _ in range(max_iters):
        draft_blob = fit_prompt_blob(
            safe_json(draft_summary(session.draft)),
            budget=min(500, in_budget // 4),
        )
        user_trim = fit_prompt_blob(user_blob, budget=min(900, in_budget // 2))
        last_trim = distill_tool_result(
            last_results, max_tokens=min(400, in_budget // 5)
        )
        packed_user, _ = _compile_user_blob(
            cfg,
            "patch",
            system=BUILD_STRUCTURED_SYSTEM,
            layers=[
                ContextLayer("task", 0, user_trim, compressible=False),
                ContextLayer("tools", 1, f"可用工具：{tool_names}", compressible=True),
                ContextLayer("draft", 2, f"当前草稿：{draft_blob}", compressible=True),
                ContextLayer("short", 3, f"上一轮：{last_trim}", compressible=True),
                ContextLayer(
                    "fixed",
                    4,
                    "输出下一轮 1～3 个 actions；完成则 [{name:done}]。勿输出解释。",
                    compressible=False,
                ),
            ],
        )
        full_msgs = [
            SystemMessage(content=BUILD_STRUCTURED_SYSTEM),
            HumanMessage(content=packed_user),
        ]
        compact_msgs = [
            SystemMessage(
                content=(
                    "输出 ToolActionBatch JSON。"
                    "字段 actions:[{name,args}]；完成用 [{name:done}]。禁止解释。"
                )
            ),
            HumanMessage(
                content=(
                    f"{fit_prompt_blob(user_blob, budget=min(500, in_budget // 3))}\n"
                    f"工具：{tool_names}\n草稿：{draft_blob}\n上一轮：{last_trim[:300]}"
                )
            ),
        ]
        try:
            batch = invoke_structured(
                llm, ToolActionBatch, full_msgs, compact_messages=compact_msgs
            )
        except Exception as exc:
            proc.append(
                {
                    "kind": "warn",
                    "node": node,
                    "label": "结构化落图",
                    "text": _short_err(exc),
                }
            )
            break
        if hasattr(batch, "model_dump"):
            actions = list(getattr(batch, "actions", None) or [])
        elif isinstance(batch, dict):
            actions = list(batch.get("actions") or [])
        else:
            break
        if not actions:
            break

        names: list[str] = []
        for action in actions:
            if hasattr(action, "model_dump"):
                ad = action.model_dump()
            elif isinstance(action, dict):
                ad = action
            else:
                continue
            names.append(str(ad.get("name") or "").strip())
        if names and all(n.lower() == "done" for n in names if n):
            break

        result_lines: list[str] = []
        for action in actions:
            if hasattr(action, "model_dump"):
                ad = action.model_dump()
            elif isinstance(action, dict):
                ad = action
            else:
                continue
            name = str(ad.get("name") or "").strip()
            if not name or name.lower() == "done":
                continue
            args = ad.get("args") if isinstance(ad.get("args"), dict) else {}
            result = _invoke_named_tool(tool_map, name, args)
            result_lines.append(f"{name}: {str(result)[:400]}")
            _emit_tool_step(
                proc=proc,
                name=name,
                result=result,
                on_progress=on_progress,
                conversation_id=conversation_id,
                assistant_id=assistant_id,
                node=node,
            )
        if not result_lines:
            break
        last_results = distill_tool_result("\n".join(result_lines), max_tokens=500)
    return proc


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
    cfg: AiConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Build via tools: prefer JSON action protocol (no chat-template tools), then
    native bind_tools if JSON path produced nothing and native is still available.
    """
    global _NATIVE_TOOLS_UNAVAILABLE
    tool_map = {t.name: t for t in tools}
    before = len(session.draft.get("nodes") or {})
    proc = _run_structured_action_loop(
        llm=llm,
        tool_map=tool_map,
        user_blob=user_blob,
        session=session,
        on_progress=on_progress,
        conversation_id=conversation_id,
        assistant_id=assistant_id,
        proc=proc,
        max_iters=max_iters,
        cfg=cfg,
    )
    after = len(session.draft.get("nodes") or {})
    if after > before or any(
        p.get("kind") == "tool" and p.get("name") for p in proc[-30:]
    ):
        return proc
    if _NATIVE_TOOLS_UNAVAILABLE:
        return proc

    try:
        bound = llm.bind_tools(tools)
    except Exception as exc:
        _mark_native_tools_unavailable()
        proc.append(
            {
                "kind": "info",
                "node": "build_loop",
                "label": "原生 tools",
                "text": _short_err(exc),
            }
        )
        return proc

    messages: list[Any] = [
        SystemMessage(content=system),
        HumanMessage(content=user_blob),
    ]
    for _ in range(max_iters):
        try:
            ai = bound.invoke(messages)
        except Exception as exc:
            if _is_native_tools_broken(exc):
                _mark_native_tools_unavailable()
                proc.append(
                    {
                        "kind": "info",
                        "node": "build_loop",
                        "label": "原生 tools",
                        "text": _short_err(exc),
                    }
                )
                return proc
            proc.append(
                {
                    "kind": "warn",
                    "node": "build_loop",
                    "label": "工具循环",
                    "text": _short_err(exc),
                }
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
            result = _invoke_named_tool(tool_map, str(name), args)
            _emit_tool_step(
                proc=proc,
                name=str(name),
                result=result,
                on_progress=on_progress,
                conversation_id=conversation_id,
                assistant_id=assistant_id,
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
    def _broadcast_process(proc: list[dict[str, Any]]) -> None:
        if not on_progress or not proc:
            return
        on_progress(
            {
                "type": "process",
                "mode": "flow",
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
                "step": proc[-1],
                "process": list(proc),
                "node": proc[-1].get("node"),
            }
        )

    def load_context(state: FlowGraphState) -> dict[str, Any]:
        draft = state.get("draft") or empty_draft()
        artifacts = state.get("artifacts") or {"shots": {}, "points": {}}
        slots = dict(state.get("known_slots") or {})
        # Merge prior clarify answers into slots
        slots = _merge_slots(slots, state.get("clarify_answers") or {})
        prior_compact = (
            state.get("context_compact")
            if isinstance(state.get("context_compact"), dict)
            else None
        )
        raw_ctx = build_draft_context(
            draft,
            artifacts,
            allow_dangerous=bool(state.get("allow_dangerous")),
            slots=slots,
            intent=str(state.get("intent") or ""),
            compact=None,
        )
        # Dual-budget: reserve output first, then pack input to available_input
        in_budget = plan_call(cfg, "understand").available_input
        mem = MemoryRouter(conversation_id).retrieve(
            query=str(state.get("input") or ""),
            working={
                "intent": state.get("intent"),
                "known_slots": slots,
                "clarify_answers": state.get("clarify_answers") or {},
                "outline": state.get("outline"),
                "gap_hints": state.get("gap_hints") or [],
                "validation_errors": state.get("validation_errors") or [],
            },
            compact=prior_compact,
            retrieval_budget=plan_call(cfg, "understand").retrieval_budget,
        )
        ctx, compact, did_compact = maybe_compact(
            raw_ctx,
            intent=str(state.get("intent") or ""),
            known_slots=slots,
            clarify_answers=state.get("clarify_answers") or {},
            pending_clarify=state.get("clarify_questions") or [],
            outline=state.get("outline") if isinstance(state.get("outline"), dict) else {},
            gap_hints=list(state.get("gap_hints") or []),
            draft=draft,
            validation_errors=list(state.get("validation_errors") or []),
            warnings=list(state.get("warnings") or []),
            process=list(state.get("process") or []),
            user_text=str(state.get("input") or ""),
            prior_compact=prior_compact,
            budget=in_budget,
            cfg=cfg,
        )
        # Attach memory summary into compact note when present
        if compact is None and (mem.get("summary") or mem.get("episodic")):
            compact = {"compact_version": 1, "summary": mem.get("summary") or ""}
        elif isinstance(compact, dict) and mem.get("episodic"):
            note = str(compact.get("summary") or "")
            epi = mem["episodic"][:600]
            compact = {
                **compact,
                "summary": (note + ("\n" if note and epi else "") + epi)[:800],
            }
        if did_compact and compact:
            # Rebuild draft context in compact mode (no full block catalog)
            ctx = build_draft_context(
                draft,
                artifacts,
                allow_dangerous=bool(state.get("allow_dangerous")),
                slots=slots,
                intent=str(state.get("intent") or compact.get("intent") or ""),
                compact=compact,
                max_nodes=16,
                max_points=8,
            )
        step = {
            "kind": "node",
            "node": "load_context",
            "label": "加载上下文",
            "text": (
                f"节点 {draft_summary(draft).get('node_count', 0)} 个"
                + (
                    f" · 已压缩(~{estimate_tokens(ctx)} tok)"
                    if did_compact
                    else f" · ~{estimate_tokens(ctx)} tok"
                )
            ),
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress,
            proc,
            step,
            mode="flow",
            conversation_id=conversation_id,
            assistant_id=assistant_id,
        )
        if did_compact:
            proc.append(
                {
                    "kind": "think",
                    "label": "上下文压缩",
                    "text": "上下文超预算，已静默提炼结构化状态后继续（会话不变）",
                }
            )
            _broadcast_process(proc)
        return {
            "context": ctx,
            "context_compact": compact or prior_compact or {},
            "did_compact": bool(did_compact),
            "known_slots": slots,
            "process": proc,
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
            "clarify_questions": list(state.get("clarify_questions") or [])
            if state.get("resume_clarify")
            else [],
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
        prior_answer_slots = merge_and_normalize(prior_slots, answers)
        intent_tag = "other"
        uir: UnderstandIR
        try:
            ctx_blob = str(state.get("context") or "")
            compact_note = ""
            cc = state.get("context_compact")
            if isinstance(cc, dict):
                compact_note = str(cc.get("summary") or "")
            packed, _ = _compile_user_blob(
                cfg,
                "understand",
                system=UNDERSTAND_SYSTEM,
                layers=[
                    ContextLayer(
                        "task",
                        0,
                        (
                            f"话术：{user_input}\n"
                            f"已有槽位：{safe_json(prior_slots)}\n"
                            f"补充：{safe_json(answers)}"
                        ),
                        compressible=False,
                    ),
                    ContextLayer("short", 1, ctx_blob, compressible=True),
                    ContextLayer("long", 2, compact_note, compressible=True),
                ],
            )
            full_msgs = [
                SystemMessage(content=UNDERSTAND_SYSTEM),
                HumanMessage(content=packed),
            ]
            compact_msgs = [
                SystemMessage(content="输出 UnderstandIR：intent_tag,slots,missing,goals。复合话术的 goals 必须完整有序。"),
                HumanMessage(content=user_input),
            ]
            raw = _structured_with_budget(
                cfg,
                "understand",
                UnderstandIR,
                full_msgs,
                compact_messages=compact_msgs,
                temperature=0.1,
            )
            uir = (
                raw
                if isinstance(raw, UnderstandIR)
                else UnderstandIR.model_validate(raw)
            )
            intent_tag = "other"
        except Exception as exc:
            intent_tag = "other"
            uir = UnderstandIR(
                intent_tag="other",
                slots=prior_answer_slots,
                missing=[],
            )
            proc.append(
                {
                    "kind": "warn",
                    "node": "understand",
                    "label": "理解回退",
                    "text": f"话术抽槽回退：{_short_err(exc, length_retried=is_length_limit_error(exc))}",
                }
            )
        slots = merge_and_normalize(
            prior_slots, uir.slots, answers
        )
        # LLM goals are non-authoritative display hints only (SSOT is PlanIR+slots).
        task_contract = build_task_contract(user_input, list(uir.goals or []))
        reconciled_tag = reconcile_intent_tag(
            intent_tag,
            task_contract,
            utterance=user_input,
        )
        if reconciled_tag != intent_tag:
            proc.append(
                {
                    "kind": "warn",
                    "node": "understand",
                    "label": "意图纠偏",
                    "text": f"{intent_tag} 与任务目标冲突，已改为 {reconciled_tag}",
                }
            )
            intent_tag = reconciled_tag
        # Clarify from understand.missing slots only — not goal.required_ops contract.
        missing_ids = list(uir.missing or [])
        missing_ids = [m for m in missing_ids if not slots.get(m)]
        ambiguities = missing_to_questions(missing_ids)
        if answers:
            answered = set(answers.keys())
            ambiguities = [q for q in ambiguities if q.get("id") not in answered]
        intent_text = intent_tag if intent_tag != "other" else user_input[:120]
        slot_line = "、".join(f"{k}={v}" for k, v in list(slots.items())[:8]) or "（无）"
        goal_line = " → ".join(
            f"{g.action}({g.target or g.value})" for g in task_contract.goals
        ) or "（无）"
        proc.append(
            {
                "kind": "think",
                "label": "意图",
                "text": (
                    f"{intent_text}\n目标：{goal_line}\n槽位：{slot_line}"
                    + (f"\n待澄清：{len(ambiguities)} 项" if ambiguities else "")
                ),
            }
        )
        _broadcast_process(proc)
        return {
            "intent": intent_text,
            "intent_tag": intent_tag,
            "task_contract": task_contract_to_dict(task_contract),
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
        slots = merge_and_normalize(
            state.get("known_slots") or {},
            answers,
        )
        still = []
        for q in pending:
            qid = str(q.get("id") or "")
            if qid and qid in answers and str(answers[qid]).strip():
                continue
            still.append(q)
        if still:
            proc.append(
                {
                    "kind": "clarify",
                    "node": "clarify",
                    "label": "需要你确认",
                    "text": still[0].get("prompt") or "请补充信息",
                }
            )
            _broadcast_process(proc)
            return {
                "clarify_questions": still,
                "clarify_answers": answers,
                "known_slots": slots,
                "status_hint": "needs_clarify",
                "process": proc,
            }
        if resume and answers:
            proc.append(
                {
                    "kind": "think",
                    "label": "澄清已答",
                    "text": "、".join(f"{k}={v}" for k, v in answers.items() if v),
                }
            )
            _broadcast_process(proc)
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
            "text": "PlanIR…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        intent = state.get("intent") or ""
        slots = merge_and_normalize(
            state.get("known_slots") or {},
        )
        hints = list(state.get("gap_hints") or [])
        task_contract = state.get("task_contract") or build_task_contract(
            state.get("input") or intent
        ).model_dump()
        prev_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
        utterance = str(state.get("input") or intent or "")
        plan: PlanIR = PlanIR(steps=[])
        try:
            ctx_blob = str(state.get("context") or "")
            packed, _ = _compile_user_blob(
                cfg,
                "plan_ir",
                system=OUTLINE_SYSTEM,
                layers=[
                    ContextLayer(
                        "task",
                        0,
                        (
                            f"意图：{intent}\n槽位：{safe_json(slots)}\n"
                            f"补洞：{safe_json(hints)}\n"
                            f"上一版IR：{format_ir_for_prompt(prev_ir)}\n"
                            f"话术：{utterance}"
                        ),
                        compressible=False,
                    ),
                    ContextLayer("short", 1, ctx_blob, compressible=True),
                ],
            )
            full_msgs = [
                SystemMessage(content=OUTLINE_SYSTEM),
                HumanMessage(content=packed),
            ]
            compact_msgs = [
                SystemMessage(content="输出 PlanIR：steps[{op,a}]。极简。只用闭集 op。a 可为短字符串。"),
                HumanMessage(content=f"意图：{intent}\n槽位：{safe_json(slots)}\n话术：{utterance}"),
            ]
            raw = _structured_with_budget(
                cfg,
                "plan_ir",
                PlanIRDraft,
                full_msgs,
                compact_messages=compact_msgs,
                temperature=0.2,
            )
            unsupported_ops = collect_unsupported_ir_ops(raw)
            plan = parse_plan_ir(raw, slots)
            if unsupported_ops:
                hints.extend(f"不支持且未编译的动作：{op}" for op in unsupported_ops)
                proc.append(
                    {
                        "kind": "warn",
                        "node": "plan_outline",
                        "label": "能力缺口",
                        "text": "、".join(unsupported_ops),
                    }
                )
            if not plan.steps or plan_ir_looks_weak(plan, utterance=utterance):
                fallback = plan_ir_from_slots(intent, slots, utterance=utterance)
                if fallback.steps:
                    plan = fallback
                    proc.append(
                        {
                            "kind": "warn",
                            "node": "plan_outline",
                            "label": "大纲回退",
                            "text": "已用槽位投影生成 PlanIR（SSOT）",
                        }
                    )
                else:
                    proc.append(
                        {
                            "kind": "warn",
                            "node": "plan_outline",
                            "label": "大纲回退",
                            "text": "coerce 后无有效步骤，等待补齐槽位",
                        }
                    )
        except Exception as exc:
            # Salvage: never blank the SSOT solely because goals exist.
            plan = plan_ir_from_slots(intent, slots, utterance=utterance)
            proc.append(
                {
                    "kind": "warn",
                    "node": "plan_outline",
                    "label": "大纲回退",
                    "text": _short_err(exc, length_retried=is_length_limit_error(exc)),
                }
            )
        # Strip schedule if once
        t = utterance
        if any(k in t for k in ("执行一次", "马上", "立刻", "立即")) or str(
            slots.get("schedule") or ""
        ).lower() in ("false", "0", "no"):
            plan = PlanIR(
                steps=[st for st in plan.steps if st.op != "schedule"]
            )
        outline = plan_ir_to_outline(plan, summary=intent[:80], slots=slots)
        # Display contract derived from SSOT when LLM goals empty.
        if not task_contract_to_dict(task_contract).get("goals") and plan.steps:
            task_contract = derive_goals_from_plan_ir(
                plan, utterance, slots=slots
            ).model_dump()
        proc.append(
            {
                "kind": "think",
                "label": "大纲",
                "text": (
                    f"{len(plan.steps)} 步 IR\n{format_ir_for_prompt(plan)}"
                ),
            }
        )
        _broadcast_process(proc)
        return {
            "plan_ir": plan_ir_to_dict(plan),
            "outline": outline,
            "task_contract": task_contract_to_dict(task_contract),
            "gap_hints": hints,
            "known_slots": slots,
            "process": proc,
        }

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
        intent = state.get("intent") or ""
        slots = merge_and_normalize(
            state.get("known_slots") or {},
        )
        plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
        task_contract = state.get("task_contract") or build_task_contract(
            state.get("input") or intent
        ).model_dump()
        gap = gap_from_ir(
            plan_ir,
            slots,
            intent=state.get("input") or intent,
            task_contract=task_contract,
        )
        complete = bool(gap.get("complete"))
        soft = list(gap.get("soft_warnings") or [])
        proc.append(
            {
                "kind": "think",
                "label": "查漏",
                "text": "通过" if complete else f"缺：{', '.join(gap.get('missing') or [])}",
            }
        )
        _broadcast_process(proc)
        return {
            "process": proc,
            "known_slots": slots,
            "gap_rounds": rounds + (0 if complete else 1),
            "status_hint": "outline_ok" if complete else "outline_gap",
            "gap_hints": list(gap.get("hints") or gap.get("missing") or []),
            "warnings": list(state.get("warnings") or [])
            + list(gap.get("capability_gaps") or [])
            + soft
            + ([] if complete else list(gap.get("missing") or [])[:3]),
            "task_contract": task_contract_to_dict(task_contract),
            "coverage_report": gap.get("coverage") or {},
        }

    def build_loop(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "build_loop",
            "label": "逐步落图",
            "text": "IR 编译落图…",
        }
        proc = list(state.get("process") or [])
        emit_process(
            on_progress, proc, step, mode="flow",
            conversation_id=conversation_id, assistant_id=assistant_id,
        )
        # Full IR compile replaces prior draft nodes (avoid 7→15 append on replan).
        draft = _draft_shell_for_recompile(state.get("draft") or state.get("base_flow"))
        artifacts = copy.deepcopy(
            state.get("artifacts") or {"shots": {}, "points": {}}
        )
        trace = list(state.get("tool_trace") or [])
        compile_trace = list(state.get("compile_trace") or [])
        slots = merge_and_normalize(
            state.get("known_slots") or {},
        )
        plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
        applied = compile_ir(
            plan_ir,
            slots,
            draft,
            artifacts=artifacts,
            tool_trace=trace,
            compile_trace=compile_trace,
            strict_coords=bool(state.get("strict_coords", True)),
            utterance=state.get("input") or "",
            summary=str(state.get("intent") or "")[:80],
        )
        draft = applied["draft"]
        artifacts = applied["artifacts"]
        trace = applied["tool_trace"]
        compile_trace = applied.get("compile_trace") or compile_trace
        coverage_now = evaluate_task_coverage(
            state.get("task_contract"),
            plan_ir,
        )
        step_goals: dict[int, list[str]] = {}
        for goal in coverage_now.get("goals") or []:
            for step_number in goal.get("matched_steps") or []:
                step_goals.setdefault(int(step_number), []).append(str(goal.get("id") or ""))
        for event in compile_trace:
            step_id = str(event.get("step_id") or "")
            if step_id.startswith("s") and step_id[1:].isdigit():
                event["goal_ids"] = [
                    goal_id
                    for goal_id in step_goals.get(int(step_id[1:]), [])
                    if goal_id
                ]
        outline = applied.get("outline") or plan_ir_to_outline(
            plan_ir, slots=slots
        )
        for err in applied.get("errors") or []:
            proc.append(
                {
                    "kind": "warn",
                    "node": "build_loop",
                    "label": "IR编译",
                    "text": err,
                }
            )
        proc.append(
            {
                "kind": "think",
                "label": "落图",
                "text": f"IR 编译：\n{applied.get('ir_prompt') or format_ir_for_prompt(plan_ir)}",
            }
        )

        # Patch hole with tools only when compile produced nothing
        if not (draft.get("nodes") or {}):
            session = ToolSession(
                draft=draft,
                artifacts=artifacts,
                tool_trace=trace,
                capture_fn=capture_fn,
                allow_dangerous=bool(state.get("allow_dangerous")),
                strict_coords=bool(state.get("strict_coords", True)),
                allow_run_block=bool(state.get("allow_run_block")),
            )
            tools = build_orchestration_tools(session, cfg=cfg)
            try:
                patch_b = plan_call(cfg, "patch", system_text=BUILD_SYSTEM)
                llm = create_chat_model(
                    cfg,
                    temperature=0.1,
                    streaming=False,
                    max_tokens=patch_b.max_tokens,
                    for_structured=True,
                )
                proc = _run_tool_loop(
                    llm=llm,
                    tools=tools,
                    system=BUILD_SYSTEM,
                    user_blob=(
                        f"意图：{state.get('intent')}\n槽位：{safe_json(slots)}\n"
                        f"IR：{format_ir_for_prompt(plan_ir)}\n"
                        "编译无产出，请用最少工具补洞落图。"
                    ),
                    session=session,
                    on_progress=on_progress,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    proc=proc,
                    max_iters=6,
                    cfg=cfg,
                )
                draft = session.draft
                artifacts = session.artifacts
                trace = session.tool_trace
            except Exception as exc:
                proc.append(
                    {
                        "kind": "warn",
                        "node": "build_loop",
                        "label": "补洞失败",
                        "text": _short_err(exc),
                    }
                )

        ncount = len(draft.get("nodes") or {})
        proc.append(
            {
                "kind": "think",
                "label": "落图结果",
                "text": f"草稿现有 {ncount} 个节点",
            }
        )
        _broadcast_process(proc)
        warnings = list(
            dict.fromkeys(
                list(state.get("warnings") or []) + collect_coord_warnings(draft)
            )
        )
        return {
            "draft": draft,
            "artifacts": artifacts,
            "tool_trace": trace,
            "compile_trace": compile_trace,
            "coverage_report": coverage_now,
            "plan_ir": plan_ir_to_dict(normalize_plan_ir(plan_ir, slots)),
            "outline": outline,
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
        coverage = evaluate_task_coverage(
            state.get("task_contract"),
            state.get("plan_ir"),
            utterance=str(state.get("input") or state.get("intent") or ""),
        )
        # SSOT: goals/coverage never enter validation_errors (structural only).
        soft_contract = (
            list(coverage.get("missing") or [])
            + list(coverage.get("capability_gaps") or [])
            + list(coverage.get("soft_warnings") or [])
        )
        errors.extend(validate_plan_draft(state.get("plan_ir"), draft))
        # Bound clicks check
        for nid, node in nodes.items():
            if not isinstance(node, dict) or node.get("type") != "click":
                continue
            params = node.get("params") if isinstance(node.get("params"), dict) else {}
            x, y = params.get("x"), params.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if not node.get("_ai_point_ref"):
                    errors.append(f"节点 {nid} 疑似裸坐标 click")
            for value in params.values():
                if not isinstance(value, str):
                    continue
                for ref_id in re.findall(r"\{\{([^.}]+)\.[^}]+\}\}", value):
                    if ref_id not in nodes:
                        errors.append(f"节点 {nid} 引用了不存在的节点 {ref_id}")
        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(list(state.get("warnings") or []) + soft_contract))
        proc.append(
            {
                "kind": "think",
                "label": "校验",
                "text": (
                    "通过"
                    if not errors
                    else "；".join(errors[:4])
                ),
            }
        )
        _broadcast_process(proc)
        return {
            "validation_errors": errors,
            "warnings": warnings,
            "coverage_report": coverage,
            "status_hint": (
                "validation_failed"
                if errors
                and int(state.get("repair_rounds") or 0)
                >= int(state.get("max_repair_rounds") or 2)
                else state.get("status_hint") or ""
            ),
            "process": proc,
        }

    def repair(state: FlowGraphState) -> dict[str, Any]:
        step = {
            "kind": "node",
            "node": "repair",
            "label": "修复",
            "text": "确定性修补…",
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
        # Code-first: set entry if missing
        nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
        if nodes and not draft.get("entry"):
            draft = set_entry(draft, next(iter(nodes.keys())))
            proc.append(
                {
                    "kind": "info",
                    "node": "repair",
                    "label": "补入口",
                    "text": f"已设置 entry={draft.get('entry')}",
                }
            )
        session = ToolSession(
            draft=draft,
            artifacts=artifacts,
            tool_trace=list(state.get("tool_trace") or []),
            capture_fn=capture_fn,
            allow_dangerous=bool(state.get("allow_dangerous")),
            strict_coords=bool(state.get("strict_coords", True)),
            allow_run_block=bool(state.get("allow_run_block")),
        )
        # Only tool-patch structural errors; contract/coverage warnings are not repairable.
        errors = [e for e in (state.get("validation_errors") or []) if "入口" not in str(e)]
        if errors:
            proc.append(
                {
                    "kind": "info",
                    "node": "repair",
                    "label": "结构修补",
                    "text": f"{len(errors)} 项结构问题",
                }
            )
            tools = build_orchestration_tools(session, cfg=cfg)
            try:
                repair_b = plan_call(cfg, "repair", system_text=REPAIR_SYSTEM)
                llm = create_chat_model(
                    cfg,
                    temperature=0,
                    streaming=False,
                    max_tokens=repair_b.max_tokens,
                    for_structured=True,
                )
                proc = _run_tool_loop(
                    llm=llm,
                    tools=tools,
                    system=REPAIR_SYSTEM,
                    user_blob=(
                        f"校验错误：{safe_json(errors)}\n"
                        f"IR：{format_ir_for_prompt(state.get('plan_ir'))}\n"
                        "请最小修补。"
                    ),
                    session=session,
                    on_progress=on_progress,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    proc=proc,
                    max_iters=4,
                    cfg=cfg,
                )
            except Exception as exc:
                proc.append(
                    {
                        "kind": "warn",
                        "node": "repair",
                        "label": "修复失败",
                        "text": _short_err(exc),
                    }
                )
        nodes = session.draft.get("nodes") if isinstance(session.draft.get("nodes"), dict) else {}
        if nodes and not session.draft.get("entry"):
            session.draft = set_entry(session.draft, next(iter(nodes.keys())))
        _broadcast_process(proc)
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
        types = [
            str(n.get("type") or "")
            for n in (summary.get("nodes") or [])
            if isinstance(n, dict)
        ]
        weak_draft = ncount <= 1 and set(types) <= {"", "delay"}
        # Skip LLM polish for weak drafts — local models often invent "无需澄清"
        if not clarify and ncount > 0 and not weak_draft:
            try:
                sum_b = plan_call(cfg, "summarize", system_text=SUMMARIZE_SYSTEM)
                llm = create_chat_model(
                    cfg,
                    temperature=0,
                    streaming=True,
                    max_tokens=sum_b.max_tokens,
                )
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
        _broadcast_process(proc)
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
    """Compat: slots → PlanOutline via PlanIR."""
    s = merge_and_normalize(slots, utterance=intent)
    return plan_ir_to_outline(
        plan_ir_from_slots(intent, s, utterance=intent),
        summary=(intent or "")[:80],
        slots=s,
    )


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
    allow_run_block: bool = False,
    use_checkpoint: bool = True,
    clarify_answers: dict[str, Any] | None = None,
    known_slots: dict[str, str] | None = None,
    intent: str = "",
    outline: dict[str, Any] | None = None,
    plan_ir: dict[str, Any] | None = None,
    resume_clarify: bool = False,
    pending_clarify: list[dict[str, Any]] | None = None,
    context_compact: dict[str, Any] | None = None,
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
        "compile_trace": [],
        "process": [],
        "repair_rounds": 0,
        "gap_rounds": 0,
        "max_repair_rounds": 2,
        "max_gap_rounds": 2,
        "allow_dangerous": allow_dangerous,
        "allow_run_block": allow_run_block,
        "strict_coords": True,
        "clarify_answers": dict(clarify_answers or {}),
        "known_slots": dict(known_slots or {}),
        "intent": intent or "",
        "intent_tag": "",
        "task_contract": {},
        "coverage_report": {},
        "plan_ir": plan_ir if isinstance(plan_ir, dict) else {},
        "outline": outline or {},
        "clarify_questions": list(pending_clarify or []),
        "resume_clarify": bool(resume_clarify),
        "gap_hints": [],
        "status_hint": "",
        "context_compact": dict(context_compact or {}),
        "did_compact": False,
    }
    config = thread_config(conversation_id) if cp is not None else None
    final = graph.invoke(init, config=config) if config else graph.invoke(init)
    return {
        "ok": True,
        "draft": final.get("draft") or draft,
        "artifacts": final.get("artifacts") or artifacts or {"shots": {}, "points": {}},
        "process": final.get("process") or [],
        "tool_trace": final.get("tool_trace") or [],
        "compile_trace": final.get("compile_trace") or [],
        "warnings": final.get("warnings") or [],
        "reply": final.get("reply") or "",
        "clarify_questions": final.get("clarify_questions") or [],
        "intent": final.get("intent") or "",
        "intent_tag": final.get("intent_tag") or "",
        "task_contract": final.get("task_contract") or {},
        "coverage_report": final.get("coverage_report") or {},
        "known_slots": final.get("known_slots") or {},
        "plan_ir": final.get("plan_ir") or {},
        "outline": final.get("outline") or {},
        "plan": {
            "intent_summary": final.get("intent") or "",
            "task_contract": final.get("task_contract") or {},
            "outline": final.get("outline") or {},
            "plan_ir": final.get("plan_ir") or {},
        },
        "status_hint": final.get("status_hint") or "",
        "validation_errors": final.get("validation_errors") or [],
        "context_compact": final.get("context_compact") or {},
        "did_compact": bool(final.get("did_compact")),
    }
