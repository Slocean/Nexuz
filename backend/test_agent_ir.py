"""Compact Agent IR + compile_ir unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai.draft_builder import empty_draft
from backend.core.ai.graphs.agent_ir import (
    IrStep,
    PlanIR,
    UnderstandIR,
    format_ir_for_prompt,
    gap_from_ir,
    merge_and_normalize,
    missing_to_questions,
    normalize_slots,
    plan_ir_from_slots,
    plan_ir_to_outline,
)
from backend.core.ai.graphs.ir_compile import compile_ir


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_normalize_slots_aliases():
    s = normalize_slots(
        {"platform": "微信", "recipient": "文件传输助手", "content": "你好"}
    )
    assert s["window_title"] == "微信"
    assert s["contact"] == "文件传输助手"
    assert s["message"] == "你好"


def test_plan_ir_from_slots_send():
    plan = plan_ir_from_slots(
        "发消息",
        {"window_title": "微信", "contact": "张三", "message": "hi"},
    )
    ops = [st.op for st in plan.steps]
    assert ops == ["activate", "ocr_click", "type", "ocr_click"]
    assert plan.steps[1].a.get("text") == "张三"
    assert plan.steps[-1].a.get("text") == "发送"


def test_compile_ir_send_message():
    slots = {
        "window_title": "微信",
        "contact": "文件传输助手",
        "message": "你好",
    }
    plan = plan_ir_from_slots("", slots)
    out = compile_ir(plan, slots, empty_draft(), strict_coords=True)
    assert out["ok"] is True
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert "window_activate" in types
    assert "type_text" in types
    assert "ocr_recognize" in types or "click" in types
    assert out["draft"].get("entry")


def test_compile_ir_delay_type():
    plan = PlanIR(
        steps=[
            IrStep(op="wait", a={"ms": "500"}),
            IrStep(op="type", a={"text": "hi"}),
        ]
    )
    out = compile_ir(plan, {"message": "hi"}, empty_draft())
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert "delay" in types and "type_text" in types


def test_missing_to_questions():
    qs = missing_to_questions(["contact", "message", "bogus"])
    ids = [q["id"] for q in qs]
    assert ids == ["contact", "message"]
    assert all(q.get("prompt") for q in qs)


def test_gap_from_ir_complete():
    plan = plan_ir_from_slots(
        "发送",
        {"window_title": "微信", "contact": "甲", "message": "x"},
    )
    gap = gap_from_ir(
        plan,
        {"window_title": "微信", "contact": "甲", "message": "x"},
        intent="发送消息",
    )
    assert gap["complete"] is True


def test_format_ir_for_prompt():
    plan = PlanIR(steps=[IrStep(op="type", a={"text": "a"})])
    assert "type" in format_ir_for_prompt(plan)


def test_merge_and_normalize_utterance():
    s = merge_and_normalize({}, utterance="打开微信给文件传输助手给他发送：你好")
    assert s.get("window_title") == "微信"
    assert s.get("contact") == "文件传输助手"
    assert s.get("message") == "你好"


def test_plan_ir_to_outline_projection():
    plan = PlanIR(steps=[IrStep(op="activate", a={"window": "微信"})])
    outline = plan_ir_to_outline(plan, summary="t")
    assert outline["steps"][0]["block_hint"] == "window_activate"


def test_normalize_plan_ir_dedupes_send_stutter():
    from backend.core.ai.graphs.agent_ir import normalize_plan_ir

    slots = {
        "window_title": "微信",
        "contact": "文件传输助手",
        "message": "你好",
    }
    stutter = PlanIR(
        steps=[
            IrStep(op="activate", a={"window": "微信"}),
            IrStep(op="ocr_click", a={"text": "文件传输助手"}),
            IrStep(op="activate", a={"window": "微信"}),
            IrStep(op="ocr_click", a={"text": "文件传输助手"}),
            IrStep(op="type", a={"text": "你好"}),
            IrStep(op="ocr_click", a={"text": "发送"}),
        ]
    )
    cleaned = normalize_plan_ir(stutter, slots)
    ops = [st.op for st in cleaned.steps]
    assert ops == ["activate", "ocr_click", "type", "ocr_click"]
    assert cleaned.steps[1].a.get("text") == "文件传输助手"
    assert cleaned.steps[-1].a.get("text") == "发送"
