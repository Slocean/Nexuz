"""Deterministic utterance → slots (LLM-failure fallback)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.graphs.slot_extract import (
    extract_slots_from_utterance,
    outline_looks_weak,
)
from backend.core.ai.graphs.flow_graph import _fallback_outline


def test_extract_send_message_utterance():
    slots = extract_slots_from_utterance(
        "打开微信给文件传输助手给他发送：你好"
    )
    assert slots.get("window_title") == "微信"
    assert slots.get("contact") == "文件传输助手"
    assert slots.get("message") == "你好"


def test_extract_does_not_invent_contact():
    slots = extract_slots_from_utterance("帮我发一条消息")
    assert "contact" not in slots
    assert "message" not in slots


def test_fallback_outline_from_utterance_not_delay_only():
    outline = _fallback_outline(
        "打开微信给文件传输助手给他发送：你好", {}
    )
    hints = [s.get("block_hint") for s in outline["steps"]]
    assert "window_activate" in hints
    assert "ocr_click" in hints
    assert "type_text" in hints
    assert outline_looks_weak(outline) is False


def test_outline_looks_weak_delay_only():
    assert outline_looks_weak({"steps": [{"block_hint": "delay"}]}) is True
    assert outline_looks_weak({"steps": []}) is True
