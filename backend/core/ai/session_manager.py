"""Orchestrate chat: LLM + tool loop + draft persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backend.core.ai.config import get_ai_config
from backend.core.ai.conversation_store import ConversationStore, get_conversation_store
from backend.core.ai.draft_builder import clone_flow, diff_nodes, draft_summary, empty_draft
from backend.core.ai.llm_client import create_llm_client
from backend.core.ai.locate import override_point
from backend.core.ai.prompts import build_system_prompt
from backend.core.ai.tool_catalog import openai_tools
from backend.core.ai.tool_runtime import (
    ToolRuntime,
    assistant_tool_call_message,
    tool_result_message,
)
from backend.core.ai.types import ChatMessage, LlmError

MAX_TOOL_STEPS = 12
CaptureFn = Callable[..., dict[str, Any]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _latest_shot_preview(artifacts: dict[str, Any]) -> dict[str, Any] | None:
    shots = artifacts.get("shots") if isinstance(artifacts.get("shots"), dict) else {}
    if not shots:
        return None
    shot = max(shots.values(), key=lambda s: float(s.get("created_at") or 0))
    if not isinstance(shot, dict):
        return None
    return {
        "shot_id": shot.get("shot_id"),
        "width": shot.get("width"),
        "height": shot.get("height"),
        "left": shot.get("left"),
        "top": shot.get("top"),
        "data_url": shot.get("data_url"),
        "coord_space": shot.get("coord_space"),
    }


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

    def list_conversations(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self._store.list_conversations()]

    def create_conversation(self, *, title: str = "新对话") -> dict[str, Any]:
        cfg = get_ai_config()
        meta = self._store.create(title=title or "新对话", model=cfg.model)
        return meta.to_dict()

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._store.get(conversation_id)

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
        validate_fn: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> dict[str, Any]:
        conv = self._store.get(conversation_id)
        if conv is None:
            return {"ok": False, "error": "会话不存在"}
        draft = conv.get("draft") or empty_draft()
        if validate_fn is not None:
            err = validate_fn(draft)
            if err:
                return {"ok": False, "error": err}
        # Strip internal AI markers before returning canonical flow
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
        self._store.save_session_state(conversation_id, status="applied")
        return {
            "ok": True,
            "flow": clean,
            "summary": draft_summary(clean),
            "diff": diff_nodes(conv.get("base_flow"), draft),
            "warnings": self._collect_warnings(draft),
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
        base_flow: dict[str, Any] | None = None,
        attach_screenshot: bool = False,
        allow_dangerous: bool = False,
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

        # Seed draft from canvas when provided and draft empty / first bind
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

        history = conv.get("messages") or []
        llm_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(has_base_flow=bool(existing_base)),
            }
        ]
        for m in history:
            role = m.get("role")
            if role in ("user", "assistant", "system") and m.get("content"):
                llm_messages.append({"role": role, "content": str(m["content"])})
        llm_messages.append({"role": "user", "content": text})

        tools = openai_tools()
        assistant_text = ""
        steps = 0
        last_usage = None

        try:
            client = create_llm_client(cfg)
            while steps < self._max_tool_steps:
                turn = client.chat(llm_messages, tools=tools)
                last_usage = turn.usage
                if turn.content:
                    assistant_text = turn.content
                if not turn.tool_calls:
                    break
                llm_messages.append(
                    assistant_tool_call_message(turn.content or "", turn.tool_calls)
                )
                for tc in turn.tool_calls:
                    steps += 1
                    if steps > self._max_tool_steps:
                        break
                    result = runtime.execute(
                        str(tc.get("name") or ""),
                        tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {},
                        draft=draft,
                        artifacts=artifacts,
                        tool_trace=tool_trace,
                    )
                    llm_messages.append(
                        tool_result_message(
                            str(tc.get("id") or ""),
                            str(tc.get("name") or ""),
                            result,
                        )
                    )
                # Continue loop for next assistant turn after tools
            else:
                if not assistant_text:
                    assistant_text = "已达到本轮工具调用上限，请查看草稿预览后继续。"
        except LlmError as exc:
            return {"ok": False, "error": exc.message}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if not assistant_text:
            summary = draft_summary(draft)
            if summary.get("node_count"):
                assistant_text = (
                    f"已更新草稿（{summary['node_count']} 个节点）。"
                    "请预览确认后应用到画布。"
                )
            else:
                assistant_text = "好的。"

        assistant_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="assistant",
            content=assistant_text,
            timestamp=_utc_now_iso(),
        )

        meta_raw = conv.get("meta") or {}
        new_title = None
        if int(meta_raw.get("message_count") or 0) == 0:
            new_title = _title_from_message(text)

        status = "awaiting_confirm" if (draft.get("nodes") or {}) else "idle"

        # Persist messages + session state
        self._store.save_session_state(
            conversation_id,
            draft=draft,
            base_flow=existing_base if set_base else None,
            artifacts=artifacts,
            tool_trace=tool_trace[-50:],
            status=status,
            set_base_flow=set_base,
        )
        updated = self._store.append_messages(
            conversation_id,
            [user_msg, assistant_msg],
            title=new_title,
            model=cfg.model,
        )

        return {
            "ok": True,
            "conversation_id": conversation_id,
            "user_message": user_msg.to_dict(),
            "assistant_message": assistant_msg.to_dict(),
            "meta": updated.to_dict() if updated else meta_raw,
            "usage": last_usage,
            "draft_summary": draft_summary(draft),
            "diff": diff_nodes(existing_base, draft),
            "points": _points_preview(artifacts),
            "shot": _latest_shot_preview(artifacts),
            "tool_trace": tool_trace[-12:],
            "tool_steps": steps,
            "status": status,
            "warnings": self._collect_warnings(draft),
        }


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def reset_session_manager_for_tests(manager: SessionManager | None = None) -> None:
    global _manager
    _manager = manager
