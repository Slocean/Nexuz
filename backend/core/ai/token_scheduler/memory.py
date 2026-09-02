"""MemoryRouter — Working / Summary / Episodic (disk session, no vector DB)."""

from __future__ import annotations

import logging

import json
import re
from typing import Any

from backend.core.ai.token_scheduler.estimate import estimate_tokens


def working_memory_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Current-task facts rebuilt every turn (authoritative)."""
    s = state if isinstance(state, dict) else {}
    return {
        "intent": str(s.get("intent") or "")[:200],
        "intent_tag": str(s.get("intent_tag") or ""),
        "known_slots": dict(s.get("known_slots") or {}),
        "clarify_answers": dict(s.get("clarify_answers") or {}),
        "outline_summary": str((s.get("outline") or {}).get("summary") or "")
        if isinstance(s.get("outline"), dict)
        else "",
        "gap_hints": list(s.get("gap_hints") or [])[:8],
        "validation_errors": list(s.get("validation_errors") or [])[:6],
    }


def summary_memory_from_compact(compact: dict[str, Any] | None) -> str:
    if not isinstance(compact, dict):
        return ""
    note = str(compact.get("summary") or "").strip()
    intent = str(compact.get("intent") or "").strip()
    slots = compact.get("known_slots") if isinstance(compact.get("known_slots"), dict) else {}
    bits = []
    if intent:
        bits.append(f"任务摘要意图: {intent}")
    if note:
        bits.append(note[:400])
    if slots:
        bits.append("槽位: " + json.dumps(slots, ensure_ascii=False)[:300])
    return "\n".join(bits)


def _tokenize_query(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    # CJK unigrams of length 2+ and latin words
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", q)
    return words[:24]


def episodic_from_messages(
    messages: list[dict[str, Any]] | None,
    *,
    query: str = "",
    budget_tokens: int = 800,
    max_hits: int = 6,
) -> str:
    """
    Keyword-score recent conversation turns; return compact episodic snippets.
    Not a vector store — good enough for same-session continuity.
    """
    items = messages if isinstance(messages, list) else []
    if not items:
        return ""
    tokens = _tokenize_query(query)
    scored: list[tuple[int, str]] = []
    for m in items[-40:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        low = content.lower()
        score = 1
        for t in tokens:
            if t in low:
                score += 3
        # Prefer user facts
        if role == "user":
            score += 1
        snippet = f"{role}: {content[:220]}"
        scored.append((score, snippet))
    scored.sort(key=lambda x: -x[0])
    # Keep top hits that still look relevant
    picks = [s for sc, s in scored[:max_hits] if sc >= 2 or not tokens]
    if not picks and scored:
        picks = [scored[0][1]]
    out_lines: list[str] = []
    used = 0
    for p in picks:
        t = estimate_tokens(p)
        if used + t > budget_tokens:
            break
        out_lines.append(p)
        used += t
    return "\n".join(out_lines)


class MemoryRouter:
    """Assemble memory layers for ContextCompiler."""

    def __init__(self, conversation_id: str = ""):
        self.conversation_id = (conversation_id or "").strip()

    def load_messages(self) -> list[dict[str, Any]]:
        if not self.conversation_id:
            return []
        try:
            from backend.core.ai.conversation_store import get_conversation_store

            data = get_conversation_store().get(self.conversation_id)
            if not data:
                return []
            msgs = data.get("messages") or []
            return [m for m in msgs if isinstance(m, dict)]
        except Exception:
            logging.getLogger(__name__).warning("情景记忆读取失败", exc_info=True)
            return []

    def retrieve(
        self,
        *,
        query: str = "",
        working: dict[str, Any] | None = None,
        compact: dict[str, Any] | None = None,
        retrieval_budget: int = 800,
        include_episodic: bool = True,
    ) -> dict[str, str]:
        work = working_memory_from_state(working)
        summary = summary_memory_from_compact(compact)
        episodic = ""
        if include_episodic:
            episodic = episodic_from_messages(
                self.load_messages(),
                query=query or str(work.get("intent") or ""),
                budget_tokens=max(100, int(retrieval_budget)),
            )
        return {
            "working": json.dumps(work, ensure_ascii=False),
            "summary": summary,
            "episodic": episodic,
        }
