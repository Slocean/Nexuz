"""Shared LangGraph state for chat and flow orchestration."""

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
    draft: dict[str, Any]
    base_flow: dict[str, Any] | None
    artifacts: dict[str, Any]
    plan: dict[str, Any]
    needs_locate: bool
    locate_texts: list[str]
    validation_errors: list[str]
    repair_rounds: int
    max_repair_rounds: int
    warnings: list[str]
    process: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    reply: str
    error: str
    allow_dangerous: bool
    strict_coords: bool
    clarify_questions: list[dict[str, Any]]
    clarify_answers: dict[str, Any]
    status_hint: str
    prefer_vision: bool


# High-frequency blocks for context injection (avoid discovery tax).
FREQUENT_BLOCKS_HINT = """
高频积木（优先使用，不必先 list_blocks）：
- delay: params.ms 毫秒
- type_text: params.text
- key_press: keys=['enter'] key_mode=single
- click: 必须 {{绑定}} 或 point_ref，禁止裸坐标
- ocr_recognize / find_image / color_detect: 感知定位，输出 x/y
- screenshot: 截图供多模态或 OCR
- wait_until: wait_type=text + expect_text
- window_activate / schedule_trigger
技能优先：text_click, type_submit, wait_then_act, window_focus, schedule_at, find_image_click, color_click, if_text, loop_n, wechat_send_message
"""


def build_draft_context(
    draft: dict[str, Any] | None,
    artifacts: dict[str, Any] | None = None,
    *,
    allow_dangerous: bool = False,
) -> str:
    """Inject draft summary + points + AI cards + skills into planner context."""
    summary = draft_summary(draft or {})
    arts = artifacts if isinstance(artifacts, dict) else {}
    points = arts.get("points") if isinstance(arts.get("points"), dict) else {}
    point_lines = []
    for pref, pt in list(points.items())[:20]:
        if not isinstance(pt, dict):
            continue
        point_lines.append(
            f"- {pref}: ({pt.get('x')},{pt.get('y')}) "
            f"label={pt.get('label') or pt.get('matched_text') or ''} "
            f"source={pt.get('source') or ''}"
        )

    raw_nodes = (draft or {}).get("nodes") if isinstance((draft or {}).get("nodes"), dict) else {}
    node_lines = []
    for n in (summary.get("nodes") or [])[:40]:
        nid = n.get("id")
        params = {}
        node = raw_nodes.get(nid) if nid else None
        if isinstance(node, dict) and isinstance(node.get("params"), dict):
            params = {
                k: node["params"][k]
                for k in list(node["params"])[:6]
                if k in node["params"]
            }
        disconnected = not n.get("next") and summary.get("node_count", 0) > 1
        node_lines.append(
            f"- {nid}: type={n.get('type')} next={n.get('next')} "
            f"params={params} orphan_hint={disconnected}"
        )

    try:
        from backend.core.ai.ai_catalog import list_ai_block_cards

        cards = list_ai_block_cards(allow_dangerous=allow_dangerous)[:48]
        block_lines = [
            f"- {c['type']}: {c.get('description')} | keys={c.get('key_params')} | {c.get('ai_hints')}"
            for c in cards
        ]
    except Exception:
        blocks = list_blocks(allow_dangerous=allow_dangerous)[:40]
        block_lines = [
            f"- {b.get('type')}: {b.get('label')}（{b.get('category')}）" for b in blocks
        ]

    try:
        from backend.core.ai.skills.loader import list_skills

        skill_lines = [
            f"- {s['id']}: {s.get('description')}" for s in list_skills()[:30]
        ]
    except Exception:
        skill_lines = []

    parts = [
        FREQUENT_BLOCKS_HINT.strip(),
        f"entry: {summary.get('entry')}",
        f"node_count: {summary.get('node_count')}",
        "nodes:",
        "\n".join(node_lines) or "(空)",
        "points:",
        "\n".join(point_lines) or "(无)",
        "skills:",
        "\n".join(skill_lines) or "(none)",
        "blocks:",
        "\n".join(block_lines) or "(unavailable)",
    ]
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
