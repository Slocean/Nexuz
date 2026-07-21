"""Persist AI conversations under {data_dir}/ai/conversations/.

Layout (performance-first):
  index.json                         — lean metas (includes kind)
  {cid}.json                         — messages + working draft/session state
  {cid}/orch/{message_id}.json       — full applyable orchestration result
  {cid}/shots/{shot_id}.json         — screenshot payloads (data_url) on demand

Messages keep process + lean orchestration card (no draft, no shot data_url).
Full draft lives only in orch/{message_id}.json so history load stays light
and any historical turn can be applied by message_id.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.ai.draft_builder import clone_flow, empty_draft
from backend.core.ai.types import ChatMessage, ConversationMeta, normalize_conversation_kind
from backend.paths import get_data_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ai_conversations_dir(*, create: bool = True) -> Path:
    root = get_data_dir(create=create) / "ai" / "conversations"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _empty_artifacts() -> dict[str, Any]:
    return {"shots": {}, "points": {}}


def slim_shot_preview(shot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop data_url for list/history payloads."""
    if not isinstance(shot, dict):
        return None
    out = {k: v for k, v in shot.items() if k != "data_url"}
    out["has_image"] = bool(shot.get("data_url") or shot.get("has_image"))
    return out


def lean_orchestration_card(card: dict[str, Any] | None, *, message_id: str) -> dict[str, Any] | None:
    """Keep UI-ready card without draft / image blobs."""
    if not isinstance(card, dict):
        return None
    shot = slim_shot_preview(card.get("shot") if isinstance(card.get("shot"), dict) else None)
    return {
        "summary": card.get("summary") if isinstance(card.get("summary"), dict) else {},
        "diff": card.get("diff") if isinstance(card.get("diff"), dict) else {},
        "warnings": list(card.get("warnings") or []) if isinstance(card.get("warnings"), list) else [],
        "tool_trace": list(card.get("tool_trace") or []) if isinstance(card.get("tool_trace"), list) else [],
        "points": list(card.get("points") or []) if isinstance(card.get("points"), list) else [],
        "shot": shot,
        "status": str(card.get("status") or ""),
        "has_result": True,
        "result_id": str(card.get("result_id") or message_id),
    }


class ConversationStore:
    def __init__(self, root: Path | None = None):
        self._root = root

    @property
    def root(self) -> Path:
        if self._root is not None:
            return self._root
        return ai_conversations_dir(create=True)

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _conv_path(self, conversation_id: str) -> Path:
        safe = self._validate_id(conversation_id)
        return self.root / f"{safe}.json"

    def _asset_dir(self, conversation_id: str) -> Path:
        return self.root / self._validate_id(conversation_id)

    def _orch_dir(self, conversation_id: str) -> Path:
        return self._asset_dir(conversation_id) / "orch"

    def _shot_dir(self, conversation_id: str) -> Path:
        return self._asset_dir(conversation_id) / "shots"

    def _orch_path(self, conversation_id: str, message_id: str) -> Path:
        mid = self._validate_id(message_id)
        return self._orch_dir(conversation_id) / f"{mid}.json"

    def _shot_path(self, conversation_id: str, shot_id: str) -> Path:
        sid = self._validate_id(shot_id)
        return self._shot_dir(conversation_id) / f"{sid}.json"

    @staticmethod
    def _validate_id(conversation_id: str) -> str:
        safe = (conversation_id or "").strip()
        if not safe or "/" in safe or "\\" in safe or ".." in safe:
            raise ValueError("无效的 conversation_id")
        return safe

    def _load_index(self) -> list[dict[str, Any]]:
        path = self._index_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, dict) and isinstance(data.get("conversations"), list):
            return [c for c in data["conversations"] if isinstance(c, dict)]
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
        return []

    def _save_index(self, items: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"conversations": items}
        self._index_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_conversations(self, *, kind: str | None = None) -> list[ConversationMeta]:
        items = self._load_index()
        metas = [ConversationMeta.from_dict(i) for i in items if i.get("id")]
        if kind is not None:
            want = normalize_conversation_kind(kind)
            metas = [m for m in metas if m.kind == want]
        metas.sort(key=lambda m: m.updated_at or m.created_at, reverse=True)
        return metas

    def create(
        self,
        *,
        title: str = "新对话",
        model: str = "",
        kind: str = "chat",
    ) -> ConversationMeta:
        now = _utc_now_iso()
        kind_n = normalize_conversation_kind(kind)
        default_title = "新编排" if kind_n == "flow" else "新对话"
        meta = ConversationMeta(
            id=str(uuid.uuid4()),
            title=(title or default_title).strip() or default_title,
            created_at=now,
            updated_at=now,
            model=model or "",
            message_count=0,
            kind=kind_n,
        )
        items = self._load_index()
        items.insert(0, meta.to_dict())
        self._save_index(items)
        self._write_full(
            meta.id,
            messages=[],
            draft=empty_draft(),
            base_flow=None,
            artifacts=_empty_artifacts(),
            tool_trace=[],
            status="idle",
            kind=kind_n,
        )
        return meta

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        data = self._read_full(conversation_id)
        return {
            "meta": meta.to_dict(),
            "messages": [m.to_dict() for m in data["messages"]],
            "draft": data["draft"],
            "base_flow": data["base_flow"],
            "artifacts": data["artifacts"],
            "tool_trace": data["tool_trace"],
            "status": data["status"],
        }

    def rename(self, conversation_id: str, title: str) -> ConversationMeta | None:
        self._validate_id(conversation_id)
        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["title"] = (title or "").strip() or item.get("title") or "新对话"
                item["updated_at"] = _utc_now_iso()
                self._save_index(items)
                return ConversationMeta.from_dict(item)
        return None

    def delete(self, conversation_id: str) -> bool:
        self._validate_id(conversation_id)
        items = self._load_index()
        new_items = [i for i in items if i.get("id") != conversation_id]
        if len(new_items) == len(items):
            return False
        self._save_index(new_items)
        path = self._conv_path(conversation_id)
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        asset = self._asset_dir(conversation_id)
        if asset.is_dir():
            try:
                shutil.rmtree(asset, ignore_errors=True)
            except OSError:
                pass
        return True

    def append_messages(
        self,
        conversation_id: str,
        messages: list[ChatMessage],
        *,
        title: str | None = None,
        model: str | None = None,
        draft: dict[str, Any] | None = None,
        base_flow: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
        status: str | None = None,
        update_draft: bool = False,
        update_base_flow: bool = False,
        update_artifacts: bool = False,
        update_tool_trace: bool = False,
    ) -> ConversationMeta | None:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return None
        data = self._read_full(conversation_id)
        existing = data["messages"]
        existing.extend(messages)

        new_draft = draft if update_draft and draft is not None else data["draft"]
        new_base = base_flow if update_base_flow else data["base_flow"]
        new_arts = artifacts if update_artifacts and artifacts is not None else data["artifacts"]
        new_trace = tool_trace if update_tool_trace and tool_trace is not None else data["tool_trace"]
        new_status = status if status is not None else data["status"]

        self._write_full(
            conversation_id,
            messages=existing,
            draft=new_draft,
            base_flow=new_base,
            artifacts=new_arts,
            tool_trace=new_trace,
            status=new_status,
            kind=meta.kind,
        )

        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["updated_at"] = _utc_now_iso()
                item["message_count"] = len(existing)
                item.setdefault("kind", meta.kind)
                if title:
                    item["title"] = title
                if model is not None:
                    item["model"] = model
                self._save_index(items)
                return ConversationMeta.from_dict(item)
        return meta

    def save_session_state(
        self,
        conversation_id: str,
        *,
        draft: dict[str, Any] | None = None,
        base_flow: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
        status: str | None = None,
        set_base_flow: bool = False,
    ) -> bool:
        self._validate_id(conversation_id)
        meta = self._find_meta(conversation_id)
        if meta is None:
            return False
        data = self._read_full(conversation_id)
        arts = artifacts if artifacts is not None else data["artifacts"]
        # Externalize shot blobs for faster main-file rewrites
        if artifacts is not None:
            arts = self._persist_shot_blobs(conversation_id, arts)
        self._write_full(
            conversation_id,
            messages=data["messages"],
            draft=draft if draft is not None else data["draft"],
            base_flow=base_flow if set_base_flow else data["base_flow"],
            artifacts=arts,
            tool_trace=tool_trace if tool_trace is not None else data["tool_trace"],
            status=status if status is not None else data["status"],
            kind=meta.kind,
        )
        items = self._load_index()
        for item in items:
            if item.get("id") == conversation_id:
                item["updated_at"] = _utc_now_iso()
                self._save_index(items)
                break
        return True

    def save_orchestration_result(
        self,
        conversation_id: str,
        message_id: str,
        *,
        draft: dict[str, Any],
        process: list[dict[str, Any]] | None = None,
        card: dict[str, Any] | None = None,
        base_flow: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist full applyable result beside the conversation (not in message body)."""
        self._validate_id(conversation_id)
        mid = self._validate_id(message_id)
        if self._find_meta(conversation_id) is None:
            raise ValueError("会话不存在")

        arts = artifacts if isinstance(artifacts, dict) else _empty_artifacts()
        arts = self._persist_shot_blobs(conversation_id, arts)
        lean = lean_orchestration_card(card, message_id=mid) or {
            "has_result": True,
            "result_id": mid,
            "status": "",
        }
        shot_id = None
        if isinstance(lean.get("shot"), dict):
            shot_id = lean["shot"].get("shot_id")
        if not shot_id:
            shots = arts.get("shots") if isinstance(arts.get("shots"), dict) else {}
            if shots:
                shot_id = next(iter(shots.keys()), None)

        payload = {
            "message_id": mid,
            "conversation_id": conversation_id,
            "created_at": _utc_now_iso(),
            "draft": clone_flow(draft) if isinstance(draft, dict) else empty_draft(),
            "base_flow": clone_flow(base_flow) if isinstance(base_flow, dict) else None,
            "process": list(process or []),
            "card": lean,
            "shot_id": shot_id,
            "points": lean.get("points") or [],
            "status": lean.get("status") or "",
        }
        path = self._orch_path(conversation_id, mid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return lean

    def get_orchestration_result(
        self,
        conversation_id: str,
        message_id: str,
        *,
        include_shot_image: bool = False,
    ) -> dict[str, Any] | None:
        path = self._orch_path(conversation_id, message_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        shot = None
        shot_id = data.get("shot_id")
        if shot_id:
            shot = self.get_shot(conversation_id, str(shot_id), include_image=include_shot_image)
        elif isinstance((data.get("card") or {}).get("shot"), dict):
            shot = slim_shot_preview(data["card"]["shot"])
            if include_shot_image and shot and shot.get("shot_id"):
                full = self.get_shot(conversation_id, str(shot["shot_id"]), include_image=True)
                if full:
                    shot = full
        out = dict(data)
        out["shot"] = shot
        return out

    def get_shot(
        self,
        conversation_id: str,
        shot_id: str,
        *,
        include_image: bool = True,
    ) -> dict[str, Any] | None:
        path = self._shot_path(conversation_id, shot_id)
        shot: dict[str, Any] | None = None
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    shot = raw
            except Exception:
                shot = None
        if shot is None:
            # Fallback: working session artifacts (legacy / in-memory path)
            data = self._read_full(conversation_id)
            arts = data.get("artifacts") or {}
            shots = arts.get("shots") if isinstance(arts.get("shots"), dict) else {}
            cand = shots.get(shot_id)
            if isinstance(cand, dict):
                shot = dict(cand)
        if shot is None:
            return None
        if include_image:
            return shot
        return slim_shot_preview(shot)

    def _persist_shot_blobs(
        self,
        conversation_id: str,
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        shots_in = artifacts.get("shots") if isinstance(artifacts.get("shots"), dict) else {}
        slim_shots: dict[str, Any] = {}
        for sid, shot in shots_in.items():
            if not isinstance(shot, dict):
                continue
            try:
                safe_sid = self._validate_id(str(sid))
            except ValueError:
                continue
            data_url = shot.get("data_url")
            if data_url:
                path = self._shot_path(conversation_id, safe_sid)
                path.parent.mkdir(parents=True, exist_ok=True)
                blob = {**shot, "shot_id": shot.get("shot_id") or safe_sid}
                path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
            slim = slim_shot_preview(shot) or {}
            slim["shot_id"] = shot.get("shot_id") or safe_sid
            slim_shots[safe_sid] = slim
        return {
            "shots": slim_shots,
            "points": artifacts.get("points")
            if isinstance(artifacts.get("points"), dict)
            else {},
        }

    def _hydrate_artifacts(self, conversation_id: str, artifacts: dict[str, Any]) -> dict[str, Any]:
        """Reattach data_url from shot files when needed for OCR/preview APIs."""
        shots_in = artifacts.get("shots") if isinstance(artifacts.get("shots"), dict) else {}
        hydrated: dict[str, Any] = {}
        for sid, shot in shots_in.items():
            if not isinstance(shot, dict):
                continue
            full = self.get_shot(conversation_id, str(sid), include_image=True)
            hydrated[str(sid)] = full if isinstance(full, dict) else shot
        return {
            "shots": hydrated,
            "points": artifacts.get("points")
            if isinstance(artifacts.get("points"), dict)
            else {},
        }

    def _find_meta(self, conversation_id: str) -> ConversationMeta | None:
        for item in self._load_index():
            if item.get("id") == conversation_id:
                return ConversationMeta.from_dict(item)
        return None

    def _read_full(self, conversation_id: str) -> dict[str, Any]:
        path = self._conv_path(conversation_id)
        if not path.is_file():
            return {
                "messages": [],
                "draft": empty_draft(),
                "base_flow": None,
                "artifacts": _empty_artifacts(),
                "tool_trace": [],
                "status": "idle",
                "kind": "chat",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "messages": [],
                "draft": empty_draft(),
                "base_flow": None,
                "artifacts": _empty_artifacts(),
                "tool_trace": [],
                "status": "idle",
                "kind": "chat",
            }
        if not isinstance(data, dict):
            data = {}
        raw_msgs = data.get("messages")
        messages = [
            ChatMessage.from_dict(m) for m in raw_msgs if isinstance(m, dict)
        ] if isinstance(raw_msgs, list) else []
        draft = data.get("draft")
        if not isinstance(draft, dict):
            draft = empty_draft()
        else:
            draft = clone_flow(draft)
        base_flow = data.get("base_flow") if isinstance(data.get("base_flow"), dict) else None
        artifacts = data.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = _empty_artifacts()
        else:
            artifacts = {
                "shots": artifacts.get("shots")
                if isinstance(artifacts.get("shots"), dict)
                else {},
                "points": artifacts.get("points")
                if isinstance(artifacts.get("points"), dict)
                else {},
            }
        # Hydrate images for runtime (override / get_draft preview)
        artifacts = self._hydrate_artifacts(conversation_id, artifacts)
        tool_trace = data.get("tool_trace") if isinstance(data.get("tool_trace"), list) else []
        status = str(data.get("status") or "idle")
        kind = normalize_conversation_kind(data.get("kind"))
        return {
            "messages": messages,
            "draft": draft,
            "base_flow": base_flow,
            "artifacts": artifacts,
            "tool_trace": tool_trace,
            "status": status,
            "kind": kind,
        }

    def _write_full(
        self,
        conversation_id: str,
        *,
        messages: list[ChatMessage],
        draft: dict[str, Any],
        base_flow: dict[str, Any] | None,
        artifacts: dict[str, Any],
        tool_trace: list[dict[str, Any]],
        status: str,
        kind: str = "chat",
    ) -> None:
        path = self._conv_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist shots externally; keep only lean refs in main JSON
        arts = self._persist_shot_blobs(conversation_id, artifacts)
        payload = {
            "id": conversation_id,
            "kind": normalize_conversation_kind(kind),
            "messages": [m.to_dict() for m in messages],
            "draft": draft,
            "base_flow": base_flow,
            "artifacts": arts,
            "tool_trace": tool_trace,
            "status": status,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


def reset_conversation_store_for_tests(store: ConversationStore | None = None) -> None:
    global _store
    _store = store
