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


# High-frequency blocks for context injection (avoid discovery tax).
FREQUENT_BLOCKS_HINT = """
高频积木（优先使用，不必先 list_blocks）：
- delay: params.ms 毫秒
- type_text: params.text
- key_press: params.key（如 enter）
- click: 必须 point_ref 或 {{绑定}}；coordinate_mode 常用 screen_abs / window_client
- ocr_recognize: params.match_text 可直接出坐标输出
- locate_text: 在 OCR 结果中定位文字
- if / loop: 分支与循环
"""


def build_draft_context(
    draft: dict[str, Any] | None,
    artifacts: dict[str, Any] | None = None,
    *,
    allow_dangerous: bool = False,
) -> str:
    """Inject draft summary + points + frequent blocks into planner context."""
    summary = draft_summary(draft or {})
    arts = artifacts if isinstance(artifacts, dict) else {}
    points = arts.get("points") if isinstance(arts.get("points"), dict) else {}
    point_lines = []
    for pref, pt in list(points.items())[:20]:
        if not isinstance(pt, dict):
            continue
        point_lines.append(
            f"- {pref}: ({pt.get('x')},{pt.get('y')}) "
            f"label={pt.get('label') or pt.get('matched_text') or ''}"
        )

    nodes = summary.get("nodes") or []
    node_lines = []
    for n in nodes[:40]:
        node_lines.append(
            f"- {n.get('id')}: type={n.get('type')} next={n.get('next')} "
            f"unverified={n.get('unverified_coords')}"
        )

    # Short catalog (labels only)
    try:
        blocks = list_blocks(allow_dangerous=allow_dangerous)[:40]
        block_lines = [
            f"- {b.get('type')}: {b.get('label')}（{b.get('category')}）" for b in blocks
        ]
    except Exception:
        block_lines = []

    parts = [
        FREQUENT_BLOCKS_HINT.strip(),
        f"entry: {summary.get('entry')}",
        f"node_count: {summary.get('node_count')}",
        "nodes:",
        "\n".join(node_lines) or "(空)",
        "points:",
        "\n".join(point_lines) or "(无)",
        "available_blocks_sample:",
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
