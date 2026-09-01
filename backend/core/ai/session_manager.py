"""Orchestrate chat: LangGraph graphs + draft persistence (Bridge facade)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backend.core.ai.config import get_ai_config
from backend.core.ai.conversation_store import (
    ConversationStore,
    get_conversation_store,
    lean_orchestration_card,
    slim_shot_preview,
)
from backend.core.ai.draft_builder import clone_flow, diff_nodes, draft_summary, empty_draft
from backend.core.ai.graphs.agent_ir import evaluate_task_coverage, validate_plan_draft
from backend.core.ai.graphs.chat_graph import run_chat_graph
from backend.core.ai.graphs.flow_graph import run_flow_graph
from backend.core.ai.lc.models import test_chat_model
from backend.core.ai.locate import override_point
from backend.core.ai.prompts import normalize_ai_mode
from backend.core.ai.types import ChatMessage, normalize_conversation_kind

MAX_TOOL_STEPS = 12  # retained for tests / legacy references
CaptureFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]
ValidateFn = Callable[[dict[str, Any]], str | None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _noop_progress(_ev: dict[str, Any]) -> None:
    return


def _synthesize_flow_summary(
    draft: dict[str, Any],
    process: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    summary = draft_summary(draft)
    nodes = summary.get("nodes") or []
    lines = [
        f"已完成本轮编排，草稿现有 {summary.get('node_count', 0)} 个节点"
        + (f"（入口：{summary.get('entry')}）" if summary.get("entry") else "")
        + "。"
    ]
    if nodes:
        listed = "、".join(
            f"{n.get('type') or '?'}({n.get('id')})" for n in nodes[:12]
        )
        lines.append(f"节点：{listed}" + ("…" if len(nodes) > 12 else "") + "。")
    tool_n = sum(1 for p in process if p.get("kind") == "tool")
    if tool_n:
        lines.append(f"共执行 {tool_n} 次工具调用。")
    if warnings:
        lines.append("注意：" + "；".join(warnings[:3]) + "。")
    lines.append("请查看下方草稿卡片，确认后点击「应用到画布」。")
    return "\n".join(lines)


def _title_from_message(text: str, *, max_len: int = 36) -> str:
    t = " ".join((text or "").strip().split())
    if not t:
        return "新对话"
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _points_preview(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    points = artifacts.get("points") if isinstance(artifacts.get("points"), dict) else {}
    out = []
    for pref, pt in points.items():
        if not isinstance(pt, dict):
            continue
        out.append(
            {
                "ref_id": pref,
                "x": pt.get("x"),
                "y": pt.get("y"),
                "label": pt.get("label"),
                "source": pt.get("source"),
                "shot_id": pt.get("shot_id"),
                "matched_text": pt.get("matched_text"),
                "bbox": pt.get("bbox"),
            }
        )
    return out


def _latest_shot_preview(
    artifacts: dict[str, Any],
    *,
    include_image: bool = True,
) -> dict[str, Any] | None:
    shots = artifacts.get("shots") if isinstance(artifacts.get("shots"), dict) else {}
    if not shots:
        return None
    shot = max(shots.values(), key=lambda s: float(s.get("created_at") or 0))
    if not isinstance(shot, dict):
        return None
    raw = {
        "shot_id": shot.get("shot_id"),
        "width": shot.get("width"),
        "height": shot.get("height"),
        "left": shot.get("left"),
        "top": shot.get("top"),
        "data_url": shot.get("data_url"),
        "coord_space": shot.get("coord_space"),
    }
    if include_image:
        raw["has_image"] = bool(shot.get("data_url"))
        return raw
    return slim_shot_preview(raw)


def _strip_ai_markers(draft: dict[str, Any]) -> dict[str, Any]:
    clean = clone_flow(draft)
    nodes = clean.get("nodes") if isinstance(clean.get("nodes"), dict) else {}
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        node.pop("_ai_unverified_coords", None)
        params = node.get("params")
        if isinstance(params, dict):
            params.pop("_ai_point_ref", None)
            params.pop("_ai_point_source", None)
    return clean


class SessionManager:
    def __init__(
        self,
        store: ConversationStore | None = None,
        *,
        capture_fn: CaptureFn | None = None,
        max_tool_steps: int = MAX_TOOL_STEPS,
        validate_fn: ValidateFn | None = None,
    ):
        self._store = store or get_conversation_store()
        self._capture_fn = capture_fn
        self._max_tool_steps = max_tool_steps
        self._validate_fn = validate_fn

    def set_capture_fn(self, fn: CaptureFn | None) -> None:
        self._capture_fn = fn

    def set_validate_fn(self, fn: ValidateFn | None) -> None:
        self._validate_fn = fn

    def list_conversations(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self._store.list_conversations(kind=kind)]

    def create_conversation(
        self,
        *,
        title: str = "新对话",
        kind: str = "chat",
    ) -> dict[str, Any]:
        cfg = get_ai_config()
        kind_n = normalize_conversation_kind(kind)
        default_title = "新编排" if kind_n == "flow" else "新对话"
        meta = self._store.create(
            title=title or default_title,
            model=cfg.model,
            kind=kind_n,
        )
        return meta.to_dict()

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._store.get(conversation_id)

    def get_orchestration(
        self,
        conversation_id: str,
        message_id: str,
        *,
        include_shot_image: bool = False,
    ) -> dict[str, Any]:
        data = self._store.get_orchestration_result(
            conversation_id,
            message_id,
            include_shot_image=include_shot_image,
        )
        if data is None:
            return {"ok": False, "error": "编排结果不存在"}
        card = data.get("card") if isinstance(data.get("card"), dict) else {}
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "draft": data.get("draft"),
            "summary": card.get("summary") or draft_summary(data.get("draft") or {}),
            "diff": card.get("diff") or {},
            "warnings": card.get("warnings") or [],
            "tool_trace": card.get("tool_trace") or [],
            "points": data.get("points") or card.get("points") or [],
            "shot": data.get("shot"),
            "process": data.get("process") or [],
            "status": data.get("status") or card.get("status") or "",
            "has_result": True,
            "result_id": message_id,
        }

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any] | None:
        meta = self._store.rename(conversation_id, title)
        return meta.to_dict() if meta else None

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._store.delete(conversation_id)

    def delete_conversations(self, conversation_ids: list[str]) -> int:
        ids = [str(i or "").strip() for i in (conversation_ids or []) if str(i or "").strip()]
        return self._store.delete_many(ids)

    def delete_all_conversations(self, *, kind: str | None = None) -> int:
        return self._store.delete_all(kind=kind)

    def test_connection(self) -> dict[str, Any]:
        return test_chat_model(get_ai_config())

    def get_draft(self, conversation_id: str) -> dict[str, Any]:
        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}
        artifacts = conv.get("artifacts") or {}
        draft = conv.get("draft") or empty_draft()
        base = conv.get("base_flow")
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "draft": draft,
            "summary": draft_summary(draft),
            "diff": diff_nodes(base, draft),
            "points": _points_preview(artifacts),
            "shot": _latest_shot_preview(artifacts),
            "status": conv.get("status") or "idle",
            "tool_trace": (conv.get("tool_trace") or [])[-20:],
        }

    def override_point(
        self,
        conversation_id: str,
        point_ref: str,
        x: int | float,
        y: int | float,
        *,
        rebind_nodes: bool = True,
    ) -> dict[str, Any]:
        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}
        artifacts = conv.get("artifacts") or {"shots": {}, "points": {}}
        draft = conv.get("draft") or empty_draft()
        result = override_point(artifacts, point_ref, x=x, y=y)
        if not result.get("ok"):
            return result
        if rebind_nodes:
            from backend.core.ai.locate import apply_point_to_params

            pt = (artifacts.get("points") or {}).get(point_ref)
            nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
            if isinstance(pt, dict):
                for node in nodes.values():
                    if not isinstance(node, dict):
                        continue
                    params = node.get("params") if isinstance(node.get("params"), dict) else {}
                    if params.get("_ai_point_ref") == point_ref:
                        node["params"] = apply_point_to_params(pt, params)
                        node.pop("_ai_unverified_coords", None)
        self._store.save_session_state(
            conversation_id,
            draft=draft,
            artifacts=artifacts,
            status="awaiting_confirm",
        )
        return {
            "ok": True,
            **result,
            "draft_summary": draft_summary(draft),
            "points": _points_preview(artifacts),
        }

    def cancel_draft(self, conversation_id: str) -> dict[str, Any]:
        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}
        base = conv.get("base_flow")
        draft = clone_flow(base) if base else empty_draft()
        self._store.save_session_state(
            conversation_id,
            draft=draft,
            artifacts={"shots": {}, "points": {}},
            tool_trace=[],
            status="cancelled",
        )
        return {"ok": True, "summary": draft_summary(draft)}

    def apply_draft(
        self,
        conversation_id: str,
        *,
        message_id: str | None = None,
        validate_fn: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> dict[str, Any]:
        mid = (message_id or "").strip()
        base_for_diff = None
        task_contract: dict[str, Any] = {}
        plan_ir: dict[str, Any] = {}
        stored_validation_errors: list[str] = []
        stored_status = ""
        if mid:
            orch = self._store.get_orchestration_result(
                conversation_id, mid, include_shot_image=False
            )
            if orch is None:
                return {"ok": False, "error": "历史编排结果不存在"}
            draft = orch.get("draft") or empty_draft()
            base_for_diff = orch.get("base_flow")
            card = orch.get("card") if isinstance(orch.get("card"), dict) else {}
            warnings = list(card.get("warnings") or [])
            stored_validation_errors = list(card.get("validation_errors") or [])
            stored_status = str(card.get("status") or "")
            plan = card.get("plan") if isinstance(card.get("plan"), dict) else {}
            task_contract = plan.get("task_contract") if isinstance(plan.get("task_contract"), dict) else {}
            plan_ir = plan.get("plan_ir") if isinstance(plan.get("plan_ir"), dict) else {}
        else:
            conv = self._store.get(conversation_id)
            if conv is None:
                return {"ok": False, "error": "会话不存在"}
            draft = conv.get("draft") or empty_draft()
            base_for_diff = conv.get("base_flow")
            warnings = self._collect_warnings(draft)
            stored_status = str(conv.get("status") or "")
            agent_state = conv.get("agent_state") if isinstance(conv.get("agent_state"), dict) else {}
            task_contract = agent_state.get("task_contract") if isinstance(agent_state.get("task_contract"), dict) else {}
            plan_ir = agent_state.get("plan_ir") if isinstance(agent_state.get("plan_ir"), dict) else {}

        if stored_status == "validation_failed" or stored_validation_errors:
            detail = "；".join(stored_validation_errors[:3]) or "草稿语义校验未通过"
            return {"ok": False, "error": detail}
        coverage = evaluate_task_coverage(task_contract, plan_ir)
        semantic_errors = list(coverage.get("missing") or [])
        semantic_errors.extend(validate_plan_draft(plan_ir, draft))
        if semantic_errors:
            return {"ok": False, "error": "；".join(dict.fromkeys(semantic_errors))}
        unsafe_warnings = [w for w in warnings if "未经验证" in str(w) or "裸坐标" in str(w)]
        if unsafe_warnings:
            return {"ok": False, "error": "；".join(unsafe_warnings[:3])}

        if validate_fn is not None:
            err = validate_fn(draft)
            if err:
                return {"ok": False, "error": err}
        clean = _strip_ai_markers(draft)
        if not mid:
            self._store.save_session_state(conversation_id, status="applied")
        return {
            "ok": True,
            "flow": clean,
            "summary": draft_summary(clean),
            "diff": diff_nodes(base_for_diff, draft),
            "warnings": warnings or self._collect_warnings(draft),
            "message_id": mid or None,
        }

    def _collect_warnings(self, draft: dict[str, Any]) -> list[str]:
        warnings = []
        nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
        for nid, node in nodes.items():
            if isinstance(node, dict) and node.get("_ai_unverified_coords"):
                warnings.append(f"节点 {nid} 含未经验证取点的坐标")
        return warnings

    def chat(
        self,
        conversation_id: str,
        message: str,
        *,
        mode: str = "flow",
        base_flow: dict[str, Any] | None = None,
        attach_screenshot: bool = False,
        allow_dangerous: bool = False,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Any]:
        ai_mode = normalize_ai_mode(mode)
        progress = on_progress or _noop_progress
        if ai_mode == "chat":
            return self._chat_plain(
                conversation_id, message, on_progress=progress
            )
        return self._chat_flow(
            conversation_id,
            message,
            base_flow=base_flow,
            attach_screenshot=attach_screenshot,
            allow_dangerous=allow_dangerous,
            on_progress=progress,
        )

    def _chat_plain(
        self,
        conversation_id: str,
        message: str,
        *,
        on_progress: ProgressFn,
    ) -> dict[str, Any]:
        """对话模式：LangGraph + LangChain 流式纯文本，无 tools。"""
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "消息不能为空"}

        cfg = get_ai_config()
        if not cfg.enabled:
            return {"ok": False, "error": "Flow AI 未启用，请先在设置中启用"}
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}

        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}

        now = _utc_now_iso()
        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=text,
            timestamp=now,
        )
        assistant_id = str(uuid.uuid4())
        on_progress(
            {
                "type": "start",
                "mode": "chat",
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
            }
        )

        history = conv.get("messages") or []
        try:
            out = run_chat_graph(
                conversation_id=conversation_id,
                user_text=text,
                history=history,
                cfg=cfg,
                on_progress=on_progress,
                assistant_id=assistant_id,
                use_checkpoint=True,
            )
            if not out.get("ok"):
                err = out.get("error") or "对话失败"
                on_progress(
                    {
                        "type": "error",
                        "error": err,
                        "conversation_id": conversation_id,
                        "assistant_id": assistant_id,
                    }
                )
                return {"ok": False, "error": err}
            assistant_text = out.get("reply") or "好的。"
            process = list(out.get("process") or [])
        except Exception as exc:
            on_progress(
                {
                    "type": "error",
                    "error": str(exc),
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                }
            )
            return {"ok": False, "error": str(exc)}

        agent_log = {
            "version": 1,
            "mode": "chat",
            "conversation_id": conversation_id,
            "assistant_id": assistant_id,
            "timestamp": _utc_now_iso(),
            "model": cfg.model,
            "user_text": text,
            "process": process,
            "reply": assistant_text,
        }
        assistant_msg = ChatMessage(
            id=assistant_id,
            role="assistant",
            content=assistant_text,
            timestamp=_utc_now_iso(),
            process=process,
            agent_log=agent_log,
        )

        meta_raw = conv.get("meta") or {}
        new_title = None
        if int(meta_raw.get("message_count") or 0) == 0:
            new_title = _title_from_message(text)

        updated = self._store.append_messages(
            conversation_id,
            [user_msg, assistant_msg],
            title=new_title,
            model=cfg.model,
        )
        draft = conv.get("draft") or empty_draft()
        artifacts = conv.get("artifacts") or {"shots": {}, "points": {}}
        result = {
            "ok": True,
            "conversation_id": conversation_id,
            "mode": "chat",
            "user_message": user_msg.to_dict(),
            "assistant_message": assistant_msg.to_dict(),
            "meta": updated.to_dict() if updated else meta_raw,
            "usage": None,
            "draft_summary": draft_summary(draft),
            "diff": diff_nodes(conv.get("base_flow"), draft),
            "points": _points_preview(artifacts),
            "shot": _latest_shot_preview(artifacts),
            "tool_trace": [],
            "process": process,
            "tool_steps": 0,
            "status": conv.get("status") or "idle",
            "warnings": [],
        }
        on_progress(
            {
                "type": "done",
                "mode": "chat",
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
                "assistant_message": assistant_msg.to_dict(),
            }
        )
        return result

    def _chat_flow(
        self,
        conversation_id: str,
        message: str,
        *,
        base_flow: dict[str, Any] | None = None,
        attach_screenshot: bool = False,
        allow_dangerous: bool = False,
        on_progress: ProgressFn = _noop_progress,
    ) -> dict[str, Any]:
        """编排模式：understand→clarify→outline→gap→build→validate→summarize。"""
        text = (message or "").strip()
        if not text and not attach_screenshot:
            return {"ok": False, "error": "消息不能为空"}

        cfg = get_ai_config()
        if not cfg.enabled:
            return {"ok": False, "error": "Flow AI 未启用，请先在设置中启用"}
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}

        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}

        draft = conv.get("draft") or empty_draft()
        artifacts = conv.get("artifacts") or {"shots": {}, "points": {}}
        tool_trace: list[dict[str, Any]] = list(conv.get("tool_trace") or [])
        existing_base = conv.get("base_flow")
        agent_state = dict(conv.get("agent_state") or {})
        prior_status = str(conv.get("status") or "")
        pending_clarify = list(agent_state.get("pending_clarify") or [])
        resume_clarify = prior_status == "needs_clarify" and bool(pending_clarify)

        set_base = False
        if isinstance(base_flow, dict) and base_flow.get("nodes") is not None:
            node_count = len((draft.get("nodes") or {}))
            if existing_base is None or node_count == 0:
                draft = clone_flow(base_flow)
                existing_base = clone_flow(base_flow)
                set_base = True
            elif existing_base is None:
                existing_base = clone_flow(base_flow)
                set_base = True

        # New orchestration turn: do not carry a previous awaiting_confirm AI draft
        # into context/compile (that caused duplicate chains like 7→15 nodes).
        if not resume_clarify:
            if isinstance(existing_base, dict) and existing_base.get("nodes") is not None:
                draft = clone_flow(existing_base)
            else:
                keep_name = str(draft.get("name") or "AI 草稿")
                keep_id = str(draft.get("flow_id") or "")
                keep_vars = draft.get("variables") if isinstance(draft.get("variables"), dict) else {}
                keep_schemas = (
                    draft.get("variable_schemas")
                    if isinstance(draft.get("variable_schemas"), dict)
                    else {}
                )
                draft = empty_draft(name=keep_name)
                if keep_id:
                    draft["flow_id"] = keep_id
                draft["variables"] = dict(keep_vars)
                draft["variable_schemas"] = dict(keep_schemas)

        if attach_screenshot:
            if self._capture_fn is None:
                return {"ok": False, "error": "截图能力不可用"}
            from backend.core.ai import locate as locate_mod

            cap = locate_mod.capture_to_artifact(self._capture_fn, hide_window=True)
            if not cap.get("ok"):
                return {"ok": False, "error": cap.get("error") or "截图失败"}
            art = cap["artifact"]
            artifacts.setdefault("shots", {})[art["shot_id"]] = art
            if not text:
                text = "请根据刚截取的屏幕，帮助我编排/取点。"

        now = _utc_now_iso()
        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=text,
            timestamp=now,
        )
        assistant_id = str(uuid.uuid4())
        on_progress(
            {
                "type": "start",
                "mode": "flow",
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
            }
        )

        try:
            out = run_flow_graph(
                conversation_id=conversation_id,
                user_text=text,
                draft=draft,
                artifacts=artifacts,
                base_flow=existing_base,
                cfg=cfg,
                capture_fn=self._capture_fn,
                validate_fn=self._validate_fn,
                on_progress=on_progress,
                assistant_id=assistant_id,
                allow_dangerous=bool(cfg.allow_dangerous),
                allow_run_block=bool(cfg.allow_run_block),
                use_checkpoint=True,
                known_slots=dict(agent_state.get("known_slots") or {}),
                intent=str(agent_state.get("intent") or ""),
                outline=agent_state.get("outline")
                if isinstance(agent_state.get("outline"), dict)
                else None,
                plan_ir=agent_state.get("plan_ir")
                if isinstance(agent_state.get("plan_ir"), dict)
                else None,
                resume_clarify=resume_clarify,
                pending_clarify=pending_clarify if resume_clarify else None,
                context_compact=agent_state.get("context_compact")
                if isinstance(agent_state.get("context_compact"), dict)
                else None,
            )
        except Exception as exc:
            on_progress(
                {
                    "type": "error",
                    "error": str(exc),
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                }
            )
            return {"ok": False, "error": str(exc)}

        draft = out.get("draft") or draft
        artifacts = out.get("artifacts") or artifacts
        process = list(out.get("process") or [])
        turn_tool_trace = list(out.get("tool_trace") or [])
        tool_trace = (tool_trace + turn_tool_trace)[-50:]
        warnings = list(out.get("warnings") or []) or self._collect_warnings(draft)
        assistant_text = (out.get("reply") or "").strip()
        if not assistant_text:
            assistant_text = _synthesize_flow_summary(draft, process, warnings)
            on_progress(
                {
                    "type": "delta",
                    "mode": "flow",
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                    "text": assistant_text,
                    "replace": True,
                }
            )

        clarify = list(out.get("clarify_questions") or [])
        validation_errors = list(out.get("validation_errors") or [])
        status = (
            "needs_clarify"
            if clarify
            else "validation_failed"
            if validation_errors
            else "awaiting_confirm"
            if (draft.get("nodes") or {})
            else "idle"
        )
        next_agent_state = {
            "intent": out.get("intent") or agent_state.get("intent") or "",
            "intent_tag": out.get("intent_tag") or agent_state.get("intent_tag") or "",
            "task_contract": out.get("task_contract") or agent_state.get("task_contract") or {},
            "coverage_report": out.get("coverage_report") or {},
            "known_slots": out.get("known_slots") or agent_state.get("known_slots") or {},
            "outline": out.get("outline") or agent_state.get("outline") or {},
            "plan_ir": out.get("plan_ir") or agent_state.get("plan_ir") or {},
            "pending_clarify": clarify if status == "needs_clarify" else [],
            "context_compact": out.get("context_compact")
            or agent_state.get("context_compact")
            or {},
            "compact_version": (
                (out.get("context_compact") or {}).get("compact_version")
                if isinstance(out.get("context_compact"), dict)
                else None
            )
            or agent_state.get("compact_version"),
        }
        points_prev = _points_preview(artifacts)
        # 仅在有可修正点位时带截图；OCR 绑定链不需要常驻「点位预览」
        shot_prev = (
            _latest_shot_preview(artifacts, include_image=False) if points_prev else None
        )
        orch_raw = {
            "summary": draft_summary(draft),
            "diff": diff_nodes(existing_base, draft),
            "warnings": warnings,
            "validation_errors": validation_errors,
            "tool_trace": turn_tool_trace[-12:],
            "points": points_prev,
            "shot": shot_prev,
            "status": status,
            "has_result": True,
            "result_id": assistant_id,
            "plan": out.get("plan") or {},
            "clarify_questions": clarify,
        }
        orch = lean_orchestration_card(orch_raw, message_id=assistant_id) or orch_raw
        try:
            from backend.core.ai.audit import write_audit_event

            write_audit_event(
                {
                    "event": "ai_chat_flow",
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                    "model": cfg.model,
                    "ai_enabled": bool(cfg.enabled),
                    "allow_dangerous": bool(cfg.allow_dangerous),
                    "status": status,
                    "node_count": draft_summary(draft).get("node_count"),
                    "warnings": warnings[:5],
                    "clarify": bool(clarify),
                    "plan_summary": (out.get("plan") or {}).get("intent_summary"),
                    "outline_steps": len(
                        ((out.get("outline") or {}).get("steps") or [])
                        if isinstance(out.get("outline"), dict)
                        else []
                    ),
                }
            )
        except Exception:
            pass

        agent_log = {
            "version": 1,
            "mode": "flow",
            "conversation_id": conversation_id,
            "assistant_id": assistant_id,
            "timestamp": _utc_now_iso(),
            "model": cfg.model,
            "user_text": text,
            "status": status,
            "intent": next_agent_state.get("intent") or "",
            "intent_tag": next_agent_state.get("intent_tag") or "",
            "task_contract": next_agent_state.get("task_contract") or {},
            "coverage_report": next_agent_state.get("coverage_report") or {},
            "known_slots": next_agent_state.get("known_slots") or {},
            "outline": next_agent_state.get("outline") or {},
            "plan_ir": next_agent_state.get("plan_ir") or {},
            "clarify_questions": clarify,
            "plan": out.get("plan") or {},
            "process": process,
            "tool_trace": turn_tool_trace,
            "compile_trace": list(out.get("compile_trace") or []),
            "warnings": warnings,
            "validation_errors": validation_errors,
            "draft_summary": draft_summary(draft),
            "reply": assistant_text,
            "status_hint": out.get("status_hint") or "",
            "context_compact": next_agent_state.get("context_compact") or {},
            "did_compact": bool(out.get("did_compact")),
        }
        assistant_msg = ChatMessage(
            id=assistant_id,
            role="assistant",
            content=assistant_text,
            timestamp=_utc_now_iso(),
            process=process,
            orchestration=orch,
            agent_log=agent_log,
        )

        meta_raw = conv.get("meta") or {}
        new_title = None
        if int(meta_raw.get("message_count") or 0) == 0:
            new_title = _title_from_message(text)

        self._store.save_session_state(
            conversation_id,
            draft=draft,
            base_flow=existing_base if set_base else None,
            artifacts=artifacts,
            tool_trace=tool_trace,
            status=status,
            set_base_flow=set_base,
            agent_state=next_agent_state,
        )
        self._store.save_orchestration_result(
            conversation_id,
            assistant_id,
            draft=draft,
            process=process,
            card=orch_raw,
            base_flow=existing_base,
            artifacts=artifacts,
        )
        updated = self._store.append_messages(
            conversation_id,
            [user_msg, assistant_msg],
            title=new_title,
            model=cfg.model,
        )

        orch_live = {
            **orch,
            "shot": _latest_shot_preview(artifacts, include_image=True),
        }

        result = {
            "ok": True,
            "conversation_id": conversation_id,
            "mode": "flow",
            "user_message": user_msg.to_dict(),
            "assistant_message": {
                **assistant_msg.to_dict(),
                "orchestration": orch_live,
                "agent_log": agent_log,
            },
            "meta": updated.to_dict() if updated else meta_raw,
            "usage": None,
            "draft_summary": orch["summary"],
            "diff": orch["diff"],
            "points": orch["points"],
            "shot": orch_live["shot"],
            "tool_trace": orch["tool_trace"],
            "process": process,
            "tool_steps": len(turn_tool_trace),
            "status": status,
            "warnings": warnings,
            "orchestration": orch_live,
            "agent_log": agent_log,
        }
        on_progress(
            {
                "type": "done",
                "mode": "flow",
                "conversation_id": conversation_id,
                "assistant_id": assistant_id,
                "assistant_message": result["assistant_message"],
                "orchestration": orch_live,
            }
        )
        return result



_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def reset_session_manager_for_tests(manager: SessionManager | None = None) -> None:
    global _manager
    _manager = manager
