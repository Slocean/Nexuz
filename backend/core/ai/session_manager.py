"""Orchestrate chat: LLM + tool loop + draft persistence."""

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
from backend.core.ai.llm_client import create_llm_client
from backend.core.ai.locate import override_point
from backend.core.ai.prompts import build_system_prompt, normalize_ai_mode
from backend.core.ai.tool_catalog import openai_tools
from backend.core.ai.tool_runtime import (
    ToolRuntime,
    _TOOL_LABELS,
    _args_brief,
    assistant_tool_call_message,
    tool_result_message,
)
from backend.core.ai.types import ChatMessage, LlmError, normalize_conversation_kind

MAX_TOOL_STEPS = 12
CaptureFn = Callable[..., dict[str, Any]]
ProgressFn = Callable[[dict[str, Any]], None]


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
    ):
        self._store = store or get_conversation_store()
        self._capture_fn = capture_fn
        self._max_tool_steps = max_tool_steps

    def set_capture_fn(self, fn: CaptureFn | None) -> None:
        self._capture_fn = fn

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

    def test_connection(self) -> dict[str, Any]:
        cfg = get_ai_config()
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}
        try:
            client = create_llm_client(cfg)
            turn = client.chat(
                [
                    {"role": "system", "content": "Reply with exactly: ok"},
                    {"role": "user", "content": "ping"},
                ],
            )
            return {
                "ok": True,
                "model": cfg.model,
                "reply_preview": (turn.content or "")[:200],
            }
        except LlmError as exc:
            return {"ok": False, "error": exc.message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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
        else:
            conv = self._store.get(conversation_id)
            if conv is None:
                return {"ok": False, "error": "会话不存在"}
            draft = conv.get("draft") or empty_draft()
            base_for_diff = conv.get("base_flow")
            warnings = self._collect_warnings(draft)

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
        """对话模式：流式纯文本，无 tools，不改草稿。"""
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "消息不能为空"}

        cfg = get_ai_config()
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
        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(mode="chat")}
        ]
        for m in history:
            role = m.get("role")
            if role in ("user", "assistant", "system") and m.get("content"):
                llm_messages.append({"role": role, "content": str(m["content"])})
        llm_messages.append({"role": "user", "content": text})

        process: list[dict[str, Any]] = []
        try:
            client = create_llm_client(cfg)
            stream_fn = getattr(client, "chat_stream", None)

            def _delta(ev: dict[str, Any]) -> None:
                on_progress(
                    {
                        **ev,
                        "mode": "chat",
                        "conversation_id": conversation_id,
                        "assistant_id": assistant_id,
                    }
                )

            if callable(stream_fn):
                turn = stream_fn(llm_messages, tools=None, on_delta=_delta)
            else:
                turn = client.chat(llm_messages, tools=None)
                if turn.reasoning:
                    _delta({"type": "reasoning", "text": turn.reasoning})
                if turn.content:
                    _delta({"type": "delta", "text": turn.content})

            if turn.reasoning:
                process.append(
                    {"kind": "think", "label": "思考", "text": turn.reasoning.strip()}
                )
            assistant_text = (turn.content or "").strip() or "好的。"
            usage = turn.usage
        except LlmError as exc:
            on_progress(
                {
                    "type": "error",
                    "error": exc.message,
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                }
            )
            return {"ok": False, "error": exc.message}
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

        if process and process[-1].get("kind") == "think":
            if str(process[-1].get("text") or "").strip() == assistant_text:
                process.pop()

        assistant_msg = ChatMessage(
            id=assistant_id,
            role="assistant",
            content=assistant_text,
            timestamp=_utc_now_iso(),
            process=process,
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
            "usage": usage,
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
        text = (message or "").strip()
        if not text and not attach_screenshot:
            return {"ok": False, "error": "消息不能为空"}

        cfg = get_ai_config()
        if not cfg.base_url.strip():
            return {"ok": False, "error": "未配置 Base URL"}

        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}

        draft = conv.get("draft") or empty_draft()
        artifacts = conv.get("artifacts") or {"shots": {}, "points": {}}
        tool_trace: list[dict[str, Any]] = list(conv.get("tool_trace") or [])
        existing_base = conv.get("base_flow")

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

        runtime = ToolRuntime(
            capture_fn=self._capture_fn,
            allow_dangerous=allow_dangerous,
            strict_coords=False,
        )

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

        history = conv.get("messages") or []
        llm_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    mode="flow", has_base_flow=bool(existing_base)
                ),
            }
        ]
        for m in history:
            role = m.get("role")
            if role in ("user", "assistant", "system") and m.get("content"):
                llm_messages.append({"role": role, "content": str(m["content"])})
        llm_messages.append({"role": "user", "content": text})

        tools = openai_tools()
        assistant_text = ""
        pre_tool_intro = ""
        saw_tools = False
        steps = 0
        last_usage = None
        process: list[dict[str, Any]] = []
        turn_tool_trace: list[dict[str, Any]] = []

        def _emit_process(step: dict[str, Any]) -> None:
            process.append(step)
            on_progress(
                {
                    "type": "process",
                    "mode": "flow",
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                    "step": step,
                    "process": list(process),
                }
            )

        try:
            client = create_llm_client(cfg)
            stream_fn = getattr(client, "chat_stream", None)

            def _forward_delta(ev: dict[str, Any]) -> None:
                on_progress(
                    {
                        **ev,
                        "mode": "flow",
                        "conversation_id": conversation_id,
                        "assistant_id": assistant_id,
                    }
                )

            while steps < self._max_tool_steps:
                # Prefer true SSE streaming so UI gets reasoning/content token-by-token.
                if callable(stream_fn):
                    turn = stream_fn(llm_messages, tools=tools, on_delta=_forward_delta)
                else:
                    turn = client.chat(llm_messages, tools=tools)
                    if turn.reasoning:
                        _forward_delta({"type": "reasoning", "text": turn.reasoning})
                    if turn.content:
                        _forward_delta({"type": "delta", "text": turn.content})
                last_usage = turn.usage

                if turn.reasoning:
                    # Persist final think once. Prefer updating last think step so UI
                    # process replace does not look like duplicated looping blocks.
                    think_step = {
                        "kind": "think",
                        "label": "思考",
                        "text": turn.reasoning.strip(),
                    }
                    if (
                        process
                        and process[-1].get("kind") == "think"
                        and process[-1].get("label") == "思考"
                    ):
                        process[-1] = think_step
                        on_progress(
                            {
                                "type": "process",
                                "mode": "flow",
                                "conversation_id": conversation_id,
                                "assistant_id": assistant_id,
                                "process": list(process),
                            }
                        )
                    else:
                        _emit_process(think_step)
                if turn.content and turn.tool_calls:
                    if not saw_tools:
                        pre_tool_intro = turn.content.strip()
                    _emit_process(
                        {
                            "kind": "think",
                            "label": "编排说明",
                            "text": turn.content.strip(),
                        }
                    )
                    # Intro already streamed into bubble; move it into process timeline only.
                    on_progress(
                        {
                            "type": "delta",
                            "mode": "flow",
                            "conversation_id": conversation_id,
                            "assistant_id": assistant_id,
                            "text": "",
                            "replace": True,
                        }
                    )
                if turn.content and not turn.tool_calls:
                    assistant_text = turn.content.strip()
                if not turn.tool_calls:
                    break

                saw_tools = True
                llm_messages.append(
                    assistant_tool_call_message(turn.content or "", turn.tool_calls)
                )
                for tc in turn.tool_calls:
                    steps += 1
                    if steps > self._max_tool_steps:
                        break
                    tname = str(tc.get("name") or "")
                    targs = (
                        tc.get("arguments")
                        if isinstance(tc.get("arguments"), dict)
                        else {}
                    )
                    result = runtime.execute(
                        tname,
                        targs,
                        draft=draft,
                        artifacts=artifacts,
                        tool_trace=tool_trace,
                    )
                    if tool_trace:
                        turn_tool_trace.append(tool_trace[-1])
                    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                    step = {
                        "kind": "tool",
                        "label": _TOOL_LABELS.get(tname, tname),
                        "name": tname,
                        "ok": ok,
                        "detail": _args_brief(tname, targs),
                        "summary": (
                            (tool_trace[-1].get("summary") if tool_trace else None)
                            or (result.get("error") if isinstance(result, dict) else None)
                            or "完成"
                        ),
                        "elapsed_ms": tool_trace[-1].get("elapsed_ms") if tool_trace else None,
                    }
                    _emit_process(step)
                    on_progress(
                        {
                            "type": "draft",
                            "mode": "flow",
                            "conversation_id": conversation_id,
                            "assistant_id": assistant_id,
                            "draft_summary": draft_summary(draft),
                            "diff": diff_nodes(existing_base, draft),
                        }
                    )
                    llm_messages.append(
                        tool_result_message(
                            str(tc.get("id") or ""),
                            tname,
                            result,
                        )
                    )
            else:
                if not assistant_text:
                    assistant_text = "已达到本轮工具调用上限，请查看下方草稿卡片确认。"
        except LlmError as exc:
            on_progress(
                {
                    "type": "error",
                    "error": exc.message,
                    "conversation_id": conversation_id,
                    "assistant_id": assistant_id,
                }
            )
            return {"ok": False, "error": exc.message}
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

        warnings = self._collect_warnings(draft)
        # Don't keep pre-tool intro as the only reply after tools ran
        if saw_tools and (
            not (assistant_text or "").strip()
            or (assistant_text or "").strip() == (pre_tool_intro or "").strip()
        ):
            # Prefer one streaming summary turn without tools
            try:
                llm_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "工具调用已完成。请用中文总结本次编排结果："
                            "添加/修改了哪些节点、连线关系、取点情况，以及用户需要确认什么。"
                            "不要再调用任何工具。"
                        ),
                    }
                )

                def _sum_delta(ev: dict[str, Any]) -> None:
                    on_progress(
                        {
                            **ev,
                            "mode": "flow",
                            "conversation_id": conversation_id,
                            "assistant_id": assistant_id,
                        }
                    )

                # Clear intro leftovers so summary streams into a clean bubble.
                _sum_delta({"type": "delta", "text": "", "replace": True})

                if callable(stream_fn):
                    sum_turn = stream_fn(
                        llm_messages, tools=None, on_delta=_sum_delta
                    )
                else:
                    sum_turn = client.chat(llm_messages, tools=None)
                    if sum_turn.reasoning:
                        _sum_delta({"type": "reasoning", "text": sum_turn.reasoning})
                    if sum_turn.content:
                        _sum_delta({"type": "delta", "text": sum_turn.content})
                if (sum_turn.content or "").strip():
                    assistant_text = sum_turn.content.strip()
                else:
                    assistant_text = _synthesize_flow_summary(draft, process, warnings)
                    _sum_delta({"type": "delta", "text": assistant_text, "replace": True})
            except Exception:
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

        if not (assistant_text or "").strip():
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

        status = "awaiting_confirm" if (draft.get("nodes") or {}) else "idle"
        orch_raw = {
            "summary": draft_summary(draft),
            "diff": diff_nodes(existing_base, draft),
            "warnings": warnings,
            "tool_trace": turn_tool_trace or tool_trace[-12:],
            "points": _points_preview(artifacts),
            "shot": _latest_shot_preview(artifacts, include_image=False),
            "status": status,
            "has_result": True,
            "result_id": assistant_id,
        }
        orch = lean_orchestration_card(orch_raw, message_id=assistant_id) or orch_raw

        assistant_msg = ChatMessage(
            id=assistant_id,
            role="assistant",
            content=assistant_text,
            timestamp=_utc_now_iso(),
            process=process,
            orchestration=orch,
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
            tool_trace=tool_trace[-50:],
            status=status,
            set_base_flow=set_base,
        )
        # Full draft / process live in sidecar for apply-by-message + lean history load
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

        # Live response may include shot image for immediate point confirm UI
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
            },
            "meta": updated.to_dict() if updated else meta_raw,
            "usage": last_usage,
            "draft_summary": orch["summary"],
            "diff": orch["diff"],
            "points": orch["points"],
            "shot": orch_live["shot"],
            "tool_trace": orch["tool_trace"],
            "process": process,
            "tool_steps": steps,
            "status": status,
            "warnings": warnings,
            "orchestration": orch_live,
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
