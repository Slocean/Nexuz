"""Silent context budget + structured compaction for Flow Agent.

Keeps conversation_id unchanged; only shrinks what is sent to the LLM.
Structured fields (intent/slots/outline) always win over prose summary.
"""

from __future__ import annotations

import json
import os
from typing import Any

from backend.core.ai.draft_builder import draft_summary
from backend.core.ai.token_scheduler.estimate import estimate_tokens
from backend.core.ai.token_scheduler.scheduler import plan_call

# Leave headroom for structured outputs on ~4k local models.
DEFAULT_CONTEXT_TOKEN_BUDGET = 2800
COMPACT_VERSION = 1


def context_token_budget(cfg: Any = None) -> int:
    """
    Input-side budget. Prefer dual-budget scheduler when cfg is present
    (output reserved first); env NEXUZ_AI_CONTEXT_BUDGET still overrides.
    """
    raw = os.environ.get("NEXUZ_AI_CONTEXT_BUDGET", "").strip()
    if raw:
        try:
            n = int(raw)
            if n >= 512:
                return n
        except ValueError:
            pass
    if cfg is not None:
        try:
            return int(plan_call(cfg, "understand").available_input)
        except Exception:
            pass
    return DEFAULT_CONTEXT_TOKEN_BUDGET


def build_compact_payload(
    *,
    intent: str = "",
    known_slots: dict[str, str] | None = None,
    clarify_answers: dict[str, Any] | None = None,
    pending_clarify: list[dict[str, Any]] | None = None,
    outline: dict[str, Any] | None = None,
    gap_hints: list[str] | None = None,
    draft: dict[str, Any] | None = None,
    validation_errors: list[str] | None = None,
    warnings: list[str] | None = None,
    process: list[dict[str, Any]] | None = None,
    user_text: str = "",
    prior_compact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pack durable agent state for the next LLM turn (no invented facts)."""
    summary = draft_summary(draft or {})
    steps = []
    if isinstance(outline, dict):
        for s in (outline.get("steps") or [])[:16]:
            if not isinstance(s, dict):
                continue
            steps.append(
                {
                    "id": s.get("id"),
                    "goal": s.get("goal"),
                    "block_hint": s.get("block_hint"),
                    "needs_sense": s.get("needs_sense"),
                    "match_text": s.get("match_text"),
                    "params": s.get("params") if isinstance(s.get("params"), dict) else {},
                }
            )
    process_tail: list[str] = []
    for p in (process or [])[-12:]:
        if not isinstance(p, dict):
            continue
        label = str(p.get("label") or p.get("node") or p.get("kind") or "").strip()
        text = str(p.get("text") or "").strip()
        if label and text:
            process_tail.append(f"{label}: {text[:120]}")
        elif label:
            process_tail.append(label)

    prior_summary = ""
    if isinstance(prior_compact, dict):
        prior_summary = str(prior_compact.get("summary") or "").strip()[:400]

    payload = {
        "compact_version": COMPACT_VERSION,
        "intent": (intent or "")[:200],
        "user_text": (user_text or "")[:300],
        "known_slots": {
            str(k): str(v)
            for k, v in (known_slots or {}).items()
            if v is not None and str(v).strip()
        },
        "clarify_answers": {
            str(k): str(v)
            for k, v in (clarify_answers or {}).items()
            if v is not None and str(v).strip()
        },
        "pending_clarify": [
            {
                "id": q.get("id"),
                "prompt": q.get("prompt"),
            }
            for q in (pending_clarify or [])
            if isinstance(q, dict)
        ][:6],
        "outline": {
            "summary": str((outline or {}).get("summary") or "")[:160]
            if isinstance(outline, dict)
            else "",
            "steps": steps,
        },
        "gap_hints": [str(h) for h in (gap_hints or [])[:8]],
        "draft_summary": {
            "entry": summary.get("entry"),
            "node_count": summary.get("node_count"),
            "types": [
                str(n.get("type") or "")
                for n in (summary.get("nodes") or [])[:24]
                if isinstance(n, dict)
            ],
        },
        "last_errors": [str(e) for e in (validation_errors or [])[:6]],
        "warnings": [str(w) for w in (warnings or [])[:6]],
        "process_tail": process_tail,
        "summary": prior_summary,
    }
    return payload


def render_compact_context(payload: dict[str, Any] | None) -> str:
    """Deterministic short context string from compact payload."""
    p = payload if isinstance(payload, dict) else {}
    lines = [
        "[CONTEXT_COMPACT]",
        f"intent: {p.get('intent') or '(未定)'}",
        f"user_text: {p.get('user_text') or ''}",
        f"slots: {json.dumps(p.get('known_slots') or {}, ensure_ascii=False)}",
        f"clarify_answers: {json.dumps(p.get('clarify_answers') or {}, ensure_ascii=False)}",
    ]
    pending = p.get("pending_clarify") or []
    if pending:
        lines.append(
            "pending_clarify: "
            + "; ".join(
                str(q.get("prompt") or q.get("id") or "")
                for q in pending
                if isinstance(q, dict)
            )
        )
    outline = p.get("outline") if isinstance(p.get("outline"), dict) else {}
    steps = outline.get("steps") or []
    if steps:
        step_bits = [
            str(s.get("goal") or s.get("block_hint") or s.get("id") or "")
            for s in steps
            if isinstance(s, dict)
        ]
        lines.append(f"outline: {outline.get('summary') or ''} | " + " → ".join(step_bits))
    ds = p.get("draft_summary") if isinstance(p.get("draft_summary"), dict) else {}
    lines.append(
        f"draft: entry={ds.get('entry')} nodes={ds.get('node_count')} "
        f"types={','.join(ds.get('types') or [])}"
    )
    if p.get("gap_hints"):
        lines.append("gap_hints: " + "; ".join(str(h) for h in p["gap_hints"]))
    if p.get("last_errors"):
        lines.append("errors: " + "; ".join(str(e) for e in p["last_errors"]))
    if p.get("warnings"):
        lines.append("warnings: " + "; ".join(str(w) for w in p["warnings"][:4]))
    if p.get("process_tail"):
        lines.append("recent: " + " | ".join(str(x) for x in p["process_tail"][-8:]))
    if p.get("summary"):
        lines.append(f"note: {p.get('summary')}")
    lines.append("[/CONTEXT_COMPACT]")
    return "\n".join(lines)


def _truncate_payload(payload: dict[str, Any], *, budget: int) -> dict[str, Any]:
    """Shrink payload fields until render fits budget (no LLM)."""
    out = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    # Progressive cuts
    for cut in (
        ("process_tail", 4),
        ("process_tail", 0),
        ("warnings", 2),
        ("warnings", 0),
        ("gap_hints", 2),
        ("gap_hints", 0),
        ("pending_clarify", 2),
    ):
        key, keep = cut
        if estimate_tokens(render_compact_context(out)) <= budget:
            break
        val = out.get(key)
        if isinstance(val, list):
            out[key] = val[:keep]
    outline = out.get("outline") if isinstance(out.get("outline"), dict) else {}
    steps = list(outline.get("steps") or [])
    while len(steps) > 4 and estimate_tokens(render_compact_context(out)) > budget:
        steps = steps[:-1]
        outline = {**outline, "steps": steps}
        out["outline"] = outline
    ds = out.get("draft_summary") if isinstance(out.get("draft_summary"), dict) else {}
    types = list(ds.get("types") or [])
    while len(types) > 6 and estimate_tokens(render_compact_context(out)) > budget:
        types = types[:-1]
        out["draft_summary"] = {**ds, "types": types}
    # Absolute last resort: drop prose summary
    if estimate_tokens(render_compact_context(out)) > budget:
        out["summary"] = ""
        out["user_text"] = str(out.get("user_text") or "")[:120]
    return out


def maybe_llm_tighten_summary(
    payload: dict[str, Any],
    *,
    cfg: Any = None,
    budget: int | None = None,
) -> dict[str, Any]:
    """Optional short LLM note when deterministic compact still over budget."""
    limit = budget if budget is not None else context_token_budget(cfg)
    text = render_compact_context(payload)
    if estimate_tokens(text) <= limit:
        return payload
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from backend.core.ai.lc.models import create_chat_model

        from backend.core.ai.token_scheduler.scheduler import plan_call as _plan

        tighten_budget = _plan(cfg, "tighten")
        llm = create_chat_model(
            cfg,
            temperature=0,
            streaming=False,
            max_tokens=tighten_budget.max_tokens,
        )
        from backend.core.ai.retry import with_retry

        msg = with_retry(
            lambda: llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "将编排状态压成不超过 8 句中文备忘。禁止改动或编造 slots 中的值；"
                            "只复述事实：意图、槽位、大纲步骤名、草稿节点类型、待澄清。"
                        )
                    ),
                    HumanMessage(content=text[:4000]),
                ]
            ),
            what="tighten",
        )
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            content = "".join(
                str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content
            )
        note = str(content).strip()[:500]
        if note:
            out = dict(payload)
            out["summary"] = note
            return _truncate_payload(out, budget=limit)
    except Exception:
        pass
    return _truncate_payload(payload, budget=limit)


def maybe_compact(
    raw_context: str,
    *,
    intent: str = "",
    known_slots: dict[str, str] | None = None,
    clarify_answers: dict[str, Any] | None = None,
    pending_clarify: list[dict[str, Any]] | None = None,
    outline: dict[str, Any] | None = None,
    gap_hints: list[str] | None = None,
    draft: dict[str, Any] | None = None,
    validation_errors: list[str] | None = None,
    warnings: list[str] | None = None,
    process: list[dict[str, Any]] | None = None,
    user_text: str = "",
    prior_compact: dict[str, Any] | None = None,
    budget: int | None = None,
    cfg: Any = None,
    force: bool = False,
) -> tuple[str, dict[str, Any] | None, bool]:
    """
    If raw_context exceeds budget (or force), return compact context.
    Returns (context_str, compact_payload_or_None, did_compact).
    """
    limit = budget if budget is not None else context_token_budget(cfg)
    # Prefer prior compact when resuming and raw is huge
    if isinstance(prior_compact, dict) and prior_compact.get("compact_version"):
        prior_text = render_compact_context(prior_compact)
        if force or estimate_tokens(raw_context) > limit:
            payload = build_compact_payload(
                intent=intent or str(prior_compact.get("intent") or ""),
                known_slots=known_slots or prior_compact.get("known_slots"),
                clarify_answers=clarify_answers or prior_compact.get("clarify_answers"),
                pending_clarify=pending_clarify
                if pending_clarify is not None
                else prior_compact.get("pending_clarify"),
                outline=outline or prior_compact.get("outline"),
                gap_hints=gap_hints
                if gap_hints is not None
                else prior_compact.get("gap_hints"),
                draft=draft,
                validation_errors=validation_errors,
                warnings=warnings,
                process=process,
                user_text=user_text or str(prior_compact.get("user_text") or ""),
                prior_compact=prior_compact,
            )
            payload = maybe_llm_tighten_summary(payload, cfg=cfg, budget=limit)
            return render_compact_context(payload), payload, True

    if not force and estimate_tokens(raw_context) <= limit:
        return raw_context, None, False

    payload = build_compact_payload(
        intent=intent,
        known_slots=known_slots,
        clarify_answers=clarify_answers,
        pending_clarify=pending_clarify,
        outline=outline,
        gap_hints=gap_hints,
        draft=draft,
        validation_errors=validation_errors,
        warnings=warnings,
        process=process,
        user_text=user_text,
        prior_compact=prior_compact,
    )
    if estimate_tokens(render_compact_context(payload)) > limit:
        payload = maybe_llm_tighten_summary(payload, cfg=cfg, budget=limit)
    else:
        payload = _truncate_payload(payload, budget=limit)
    return render_compact_context(payload), payload, True


def fit_prompt_blob(text: str, *, budget: int | None = None) -> str:
    """Trim a free-form prompt fragment to token budget (for node SystemMessages)."""
    limit = budget if budget is not None else min(1200, context_token_budget() // 2)
    s = text or ""
    if estimate_tokens(s) <= limit:
        return s
    # Binary-ish trim by characters
    lo, hi = 0, len(s)
    best = s[: max(200, len(s) // 4)]
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = s[:mid]
        if estimate_tokens(cand) <= limit:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best.rstrip() + "\n…(truncated)"
