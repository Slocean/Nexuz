"""Plan2–5 platform gates: skills, catalog, vision infer, audit, dangerous deny."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_safe_blocks_have_ai_cards():
    from backend.core.ai.ai_catalog import coverage_report

    report = coverage_report(allow_dangerous=False)
    assert report["ok"] is True, report
    assert report["count"] >= 20
    assert not report["missing_description"]


def test_skills_loaded():
    from backend.core.ai.skills.loader import list_skills, reload_skills

    reload_skills()
    skills = list_skills(include_disabled=True)
    ids = {s["id"] for s in skills}
    assert "text_click" in ids
    assert "wechat_send_message" in ids
    assert "schedule_at" in ids
    assert len(skills) >= 6


def test_infer_supports_vision():
    from backend.core.ai.vision_locate import infer_supports_vision

    assert infer_supports_vision("gpt-4o") is True
    assert infer_supports_vision("qwen2.5-vl-7b") is True
    assert infer_supports_vision("qwen2.5-7b") is False


def test_wechat_skill_expand():
    from backend.core.ai.draft_builder import empty_draft
    from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text

    plan = heuristic_plan_from_text("明天 9 点用微信给联系人甲发消息「测试内容A」")
    assert any(s.recipe == "wechat_send_message" for s in plan.steps)
    assert plan.steps[0].params.get("contact") == "联系人甲"
    assert plan.steps[0].params.get("message") == "测试内容A"
    assert plan.steps[0].params.get("window_title") == "微信"
    draft = empty_draft()
    out = apply_flow_spec(draft, plan, strict_coords=True)
    types = [
        n.get("type")
        for n in (out["draft"].get("nodes") or {}).values()
        if isinstance(n, dict)
    ]
    assert "schedule_trigger" in types
    assert "window_activate" in types
    assert "ocr_recognize" in types
    assert "type_text" in types
    assert out.get("needs_locate") is False


def test_wechat_once_params_from_utterance_not_defaults():
    from backend.core.ai.draft_builder import empty_draft
    from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text

    utt = "打开微信给联系人乙发送一条「测试内容B」执行一次"
    plan = heuristic_plan_from_text(utt)
    assert plan.clarify_questions == []
    step = plan.steps[0]
    assert step.params.get("schedule") is False
    assert step.params.get("message") == "测试内容B"
    assert step.params.get("contact") == "联系人乙"
    assert step.params.get("window_title") == "微信"
    # Missing contact must error — no silent demo default
    out_bad = apply_flow_spec(
        empty_draft(),
        {
            "steps": [
                {
                    "action": "call_skill",
                    "recipe": "wechat_send_message",
                    "params": {"message": "x", "window_title": "微信"},
                }
            ]
        },
        strict_coords=True,
    )
    assert out_bad.get("errors")
    assert "contact" in str(out_bad["errors"]).lower() or "contact" in "".join(
        out_bad["errors"]
    )
    out = apply_flow_spec(empty_draft(), plan, strict_coords=True)
    types = [
        n.get("type")
        for n in (out["draft"].get("nodes") or {}).values()
        if isinstance(n, dict)
    ]
    assert "schedule_trigger" not in types
    assert "type_text" in types


def test_wechat_missing_message_clarifies_not_default_hello():
    from backend.core.ai.graphs.recipes import heuristic_plan_from_text

    plan = heuristic_plan_from_text("帮我给联系人甲发一条微信")
    assert plan.steps == []
    assert any(q.id == "message" for q in plan.clarify_questions)


def test_path_b_no_raw_coords():
    from backend.core.ai.draft_builder import empty_draft, params_need_coord_refs
    from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text

    plan = heuristic_plan_from_text("点击「登录」")
    draft = empty_draft()
    out = apply_flow_spec(draft, plan, strict_coords=True)
    for node in (out["draft"].get("nodes") or {}).values():
        if isinstance(node, dict) and node.get("type") == "click":
            assert not params_need_coord_refs(node.get("params") or {})


def test_dangerous_block_denied():
    from backend.core.ai.tool_catalog import is_block_allowed

    assert is_block_allowed("run_command", allow_dangerous=False) is False
    assert is_block_allowed("delay", allow_dangerous=False) is True


def test_audit_write_read(tmp_path, monkeypatch):
    from backend.core.ai import audit

    monkeypatch.setattr(audit, "_audit_dir", lambda create=True: tmp_path)
    audit.write_audit_event({"event": "test_orch", "skill": "text_click"})
    events = audit.list_recent_audit(limit=10)
    assert events
    assert events[0].get("event") == "test_orch"
