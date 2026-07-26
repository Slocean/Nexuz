"""Shared LangGraph state for chat and step-wise flow Agent."""

from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from backend.core.ai.draft_builder import draft_summary
from backend.core.ai.tool_catalog import list_blocks


class ChatGraphState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    input: str
    reply: str
    error: str


class FlowGraphState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    input: str
    context: str
    context_compact: dict[str, Any]
    did_compact: bool
    draft: dict[str, Any]
    base_flow: dict[str, Any] | None
    artifacts: dict[str, Any]
    # Step-wise agent
    intent: str
    intent_tag: str
    task_contract: dict[str, Any]
    coverage_report: dict[str, Any]
    known_slots: dict[str, str]
    plan_ir: dict[str, Any]
    outline: dict[str, Any]
    gap_rounds: int
    max_gap_rounds: int
    build_rounds: int
    # Clarify / status
    clarify_questions: list[dict[str, Any]]
    clarify_answers: dict[str, Any]
    resume_clarify: bool
    gap_hints: list[str]
    status_hint: str
    # Validation
    validation_errors: list[str]
    repair_rounds: int
    max_repair_rounds: int
    warnings: list[str]
    process: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    compile_trace: list[dict[str, Any]]
    reply: str
    error: str
    allow_dangerous: bool
    strict_coords: bool
    prefer_vision: bool
    # Legacy fields (compat)
    plan: dict[str, Any]
    needs_locate: bool
    locate_texts: list[str]


FREQUENT_BLOCKS_HINT = """
高频积木（落图时优先）：
- delay / type_text / key_press
- window_activate / schedule_trigger
- ocr_recognize → click 绑定 {{id.x}}/{{id.y}}（禁止裸坐标）
- find_image / color_detect / screenshot / wait_until
可选工具 call_skill：标准宏（非必须）
"""


def build_draft_context(
    draft: dict[str, Any] | None,
    artifacts: dict[str, Any] | None = None,
    *,
    allow_dangerous: bool = False,
    slots: dict[str, str] | None = None,
    intent: str = "",
    compact: dict[str, Any] | None = None,
    max_nodes: int = 24,
    max_points: int = 12,
    max_blocks: int = 24,
    max_skills: int = 12,
) -> str:
    """
    Build LLM context for orchestration.
    When ``compact`` is set, skip full block catalog and prefer compact body.
    """
    summary = draft_summary(draft or {})
    arts = artifacts if isinstance(artifacts, dict) else {}
    points = arts.get("points") if isinstance(arts.get("points"), dict) else {}
    point_lines = []
    for pref, pt in list(points.items())[:max_points]:
        if not isinstance(pt, dict):
            continue
        point_lines.append(
            f"- {pref}: ({pt.get('x')},{pt.get('y')}) "
            f"label={pt.get('label') or pt.get('matched_text') or ''} "
            f"source={pt.get('source') or ''}"
        )

    raw_nodes = (draft or {}).get("nodes") if isinstance((draft or {}).get("nodes"), dict) else {}
    node_lines = []
    for n in (summary.get("nodes") or [])[:max_nodes]:
        nid = n.get("id")
        params = {}
        node = raw_nodes.get(nid) if nid else None
        if isinstance(node, dict) and isinstance(node.get("params"), dict):
            params = {
                k: node["params"][k]
                for k in list(node["params"])[:6]
                if k in node["params"]
            }
        node_lines.append(
            f"- {nid}: type={n.get('type')} next={n.get('next')} params={params}"
        )

    use_compact = isinstance(compact, dict) and bool(compact.get("compact_version"))
    block_lines: list[str] = []
    skill_lines: list[str] = []
    if not use_compact:
        try:
            from backend.core.ai.ai_catalog import list_ai_block_cards

            cards = list_ai_block_cards(allow_dangerous=allow_dangerous)[:max_blocks]
            block_lines = [
                f"- {c['type']}: {c.get('description')} | keys={c.get('key_params')}"
                for c in cards
            ]
        except Exception:
            blocks = list_blocks(allow_dangerous=allow_dangerous)[:max_blocks]
            block_lines = [
                f"- {b.get('type')}: {b.get('label')}（{b.get('category')}）"
                for b in blocks
            ]

        try:
            from backend.core.ai.skills.loader import list_skills

            skill_lines = [
                f"- {s['id']}: {s.get('description')}"
                for s in list_skills()[:max_skills]
            ]
        except Exception:
            skill_lines = []

    parts = [FREQUENT_BLOCKS_HINT.strip()]
    if use_compact:
        try:
            from backend.core.ai.context_budget import render_compact_context

            parts.append(render_compact_context(compact))
        except Exception:
            parts.append(json.dumps(compact, ensure_ascii=False)[:2000])
    else:
        parts.extend(
            [
                f"intent: {intent or '(未定)'}",
                f"slots: {json.dumps(slots or {}, ensure_ascii=False)}",
            ]
        )
    parts.extend(
        [
            f"entry: {summary.get('entry')}",
            f"node_count: {summary.get('node_count')}",
            "nodes:",
            "\n".join(node_lines) or "(空)",
            "points:",
            "\n".join(point_lines) or "(无)",
        ]
    )
    if not use_compact:
        parts.extend(
            [
                "optional_skills:",
                "\n".join(skill_lines) or "(none)",
                "blocks:",
                "\n".join(block_lines) or "(unavailable)",
            ]
        )
    else:
        parts.append("blocks: (compact mode — use frequent hints / call_skill)")
    return "\n".join(parts)


def collect_coord_warnings(draft: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = []
    nodes = (draft or {}).get("nodes") if isinstance((draft or {}).get("nodes"), dict) else {}
    for nid, node in nodes.items():
        if isinstance(node, dict) and node.get("_ai_unverified_coords"):
            warnings.append(f"节点 {nid} 含未经验证取点的坐标")
    return warnings


def safe_json(data: Any, *, limit: int = 6000) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    except Exception:
        s = str(data)
    return s[:limit]
