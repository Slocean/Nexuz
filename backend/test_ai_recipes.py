"""Tests for FlowSpec recipes and context injection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai.draft_builder import empty_draft
from backend.core.ai.graphs.recipes import apply_flow_spec, heuristic_plan_from_text
from backend.core.ai.graphs.state import build_draft_context
from backend.core.ai.lc.structured import FlowSpec, PlanStep
from backend.core.ai.tool_runtime import ToolRuntime


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_heuristic_delay_type():
    plan = heuristic_plan_from_text("先等待 1 秒，输入 hello")
    assert any(s.action == "delay" for s in plan.steps)
    assert any(s.action == "type_text" for s in plan.steps)
    out = apply_flow_spec(empty_draft(), plan)
    assert out["ok"] is True
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert types == ["delay", "type_text"] or set(types) >= {"delay", "type_text"}
    # connected
    nodes = out["draft"]["nodes"]
    delay_id = next(i for i, n in nodes.items() if n["type"] == "delay")
    type_id = next(i for i, n in nodes.items() if n["type"] == "type_text")
    assert nodes[delay_id]["next"] == type_id


def test_ocr_click_recipe_bindings():
    plan = FlowSpec(
        intent_summary="点击登录",
        needs_locate=True,
        locate_texts=["登录"],
        steps=[
            PlanStep(
                action="ocr_click",
                match_text="登录",
                params={"window_title": "微信"},
            )
        ],
    )
    out = apply_flow_spec(empty_draft(), plan, strict_coords=True)
    assert out["ok"] is True
    types = [n["type"] for n in (out["draft"].get("nodes") or {}).values()]
    assert "ocr_recognize" in types
    assert "click" in types
    ocr = next(n for n in out["draft"]["nodes"].values() if n["type"] == "ocr_recognize")
    assert ocr["params"].get("match_text") == "登录"
    assert ocr["params"].get("window_title") == "微信"
    assert ocr["params"].get("output_coordinate_mode") == "screen_abs"
    # Region intentionally empty — runtime resolves window/fullscreen
    assert not ocr["params"].get("region")
    click = next(n for n in out["draft"]["nodes"].values() if n["type"] == "click")
    assert "{{" in str(click["params"].get("x"))
    assert click.get("_ai_unverified_coords") is not True


def test_ocr_region_fallback_uses_match_not_tiny_box(monkeypatch):
    from backend.blocks import ocr_recognize as ocr_mod

    monkeypatch.setattr(
        ocr_mod,
        "_region_from_window_hint",
        lambda _p: None,
    )
    monkeypatch.setattr(
        "backend.blocks._helpers.virtual_screen_size",
        lambda: (0, 0, 1920, 1080),
    )
    region, _ = ocr_mod.resolve_ocr_region({"match_text": "发送"})
    assert region == (0, 0, 1920, 1080)


def test_strict_coords_default_rejects_raw():
    rt = ToolRuntime(strict_coords=True)
    draft = empty_draft()
    res = rt.execute(
        "draft_add_node",
        {"type": "click", "params": {"x": 100, "y": 200}},
        draft=draft,
        artifacts={"shots": {}, "points": {}},
        tool_trace=[],
    )
    assert res["ok"] is False
    assert "point_ref" in (res.get("error") or "")


def test_context_includes_draft_nodes():
    draft = empty_draft()
    from backend.core.ai import draft_builder

    draft, nid = draft_builder.add_node(draft, block_type="delay", params={"ms": 500})
    ctx = build_draft_context(draft, {"points": {}})
    assert nid in ctx
    assert "delay" in ctx
    assert "高频积木" in ctx
