"""Silent context budget / compaction tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.context_budget import (
    build_compact_payload,
    estimate_tokens,
    maybe_compact,
    render_compact_context,
)
from backend.core.ai.draft_builder import empty_draft
from backend.core.ai.graphs.state import build_draft_context
from backend.core.registry import register_all_blocks


def test_estimate_tokens_positive():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("打开微信给文件传输助手发送你好") > 5


def test_maybe_compact_under_budget_noop():
    short = "intent: demo\nslots: {}\nnodes: (空)"
    ctx, compact, did = maybe_compact(
        short,
        intent="demo",
        known_slots={"message": "hi"},
        budget=5000,
    )
    assert did is False
    assert compact is None
    assert ctx == short


def test_maybe_compact_over_budget_keeps_slots():
    fat = "BLOCK\n" * 4000 + "useless catalog " * 500
    ctx, compact, did = maybe_compact(
        fat,
        intent="发消息",
        known_slots={
            "contact": "文件传输助手",
            "message": "你好",
            "window_title": "微信",
        },
        outline={
            "summary": "send",
            "steps": [
                {"id": "s1", "goal": "激活", "block_hint": "window_activate"},
                {"id": "s2", "goal": "点联系人", "block_hint": "ocr_click", "match_text": "文件传输助手"},
            ],
        },
        user_text="打开微信给文件传输助手发送：你好",
        budget=400,
        cfg=None,
    )
    assert did is True
    assert isinstance(compact, dict)
    assert compact["known_slots"]["contact"] == "文件传输助手"
    assert compact["known_slots"]["message"] == "你好"
    assert compact["known_slots"]["window_title"] == "微信"
    assert estimate_tokens(ctx) < estimate_tokens(fat)
    assert "CONTEXT_COMPACT" in ctx
    assert "文件传输助手" in ctx


def test_build_draft_context_compact_skips_block_catalog():
    register_all_blocks()
    draft = empty_draft()
    fat = build_draft_context(draft, {"shots": {}, "points": {}}, intent="x")
    payload = build_compact_payload(
        intent="发消息",
        known_slots={"window_title": "微信", "message": "hi"},
        draft=draft,
        user_text="hi",
    )
    slim = build_draft_context(
        draft,
        {"shots": {}, "points": {}},
        intent="发消息",
        compact=payload,
    )
    assert "CONTEXT_COMPACT" in slim
    assert "compact mode" in slim
    assert estimate_tokens(slim) < estimate_tokens(fat)
    assert "微信" in slim


def test_render_compact_roundtrip():
    payload = build_compact_payload(
        intent="i",
        known_slots={"a": "1"},
        outline={"summary": "s", "steps": [{"goal": "g", "block_hint": "delay"}]},
    )
    text = render_compact_context(payload)
    assert "intent: i" in text
    assert '"a": "1"' in text or "a" in text
