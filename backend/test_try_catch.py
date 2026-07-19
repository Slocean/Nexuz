"""Interpreter try_catch control-flow coverage."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.interpreter import FlowInterpreter


def _handlers(order: list[str], *, boom_ids: set[str] | None = None):
    boom_ids = boom_ids or set()

    def handler(_params, _context, **kwargs):
        node_id = str(kwargs.get("node_id") or "")
        order.append(node_id)
        if node_id in boom_ids:
            raise RuntimeError(f"boom:{node_id}")
        return {"ok": True}

    return handler


def test_try_catch_success_skips_catch_runs_finally():
    order: list[str] = []
    flow = {
        "entry": "t",
        "nodes": {
            "t": {
                "type": "try_catch",
                "params": {},
                "body": "ok",
                "catch": "catch",
                "finally": "fin",
                "next": "done",
            },
            "ok": {"type": "stub", "params": {}, "next": None},
            "catch": {"type": "stub", "params": {}, "next": None},
            "fin": {"type": "stub", "params": {}, "next": None},
            "done": {"type": "stub", "params": {}, "next": None},
        },
    }
    with patch("backend.core.interpreter.get_handler", side_effect=lambda t: _handlers(order)):
        ctx = FlowInterpreter()._execute(flow)
    assert order == ["t", "ok", "t", "fin", "t", "done"]
    assert ctx.get("t.raised") is False
    assert ctx.get("t.error") == ""


def test_try_catch_routes_error_to_catch_then_finally():
    order: list[str] = []
    flow = {
        "entry": "t",
        "nodes": {
            "t": {
                "type": "try_catch",
                "params": {},
                "body": "bad",
                "catch": "catch",
                "finally": "fin",
                "next": "done",
            },
            "bad": {"type": "stub", "params": {}, "next": None},
            "catch": {"type": "stub", "params": {}, "next": None},
            "fin": {"type": "stub", "params": {}, "next": None},
            "done": {"type": "stub", "params": {}, "next": None},
        },
    }
    with patch(
        "backend.core.interpreter.get_handler",
        side_effect=lambda t: _handlers(order, boom_ids={"bad"}),
    ):
        ctx = FlowInterpreter()._execute(flow)
    assert order == ["t", "bad", "catch", "t", "fin", "t", "done"]
    assert ctx.get("t.raised") is True
    assert "boom:bad" in str(ctx.get("t.error") or "")


def test_try_catch_finally_only_reraises_without_catch():
    order: list[str] = []
    flow = {
        "entry": "t",
        "nodes": {
            "t": {
                "type": "try_catch",
                "params": {},
                "body": "bad",
                "finally": "fin",
                "next": "done",
            },
            "bad": {"type": "stub", "params": {}, "next": None},
            "fin": {"type": "stub", "params": {}, "next": None},
            "done": {"type": "stub", "params": {}, "next": None},
        },
    }
    with patch(
        "backend.core.interpreter.get_handler",
        side_effect=lambda t: _handlers(order, boom_ids={"bad"}),
    ):
        with pytest.raises(RuntimeError, match="boom:bad"):
            FlowInterpreter()._execute(flow)
    assert order == ["t", "bad", "fin", "t"]
    assert "done" not in order


def test_try_catch_nested_inner_handles_first():
    order: list[str] = []
    flow = {
        "entry": "outer",
        "nodes": {
            "outer": {
                "type": "try_catch",
                "params": {},
                "body": "inner",
                "catch": "outer_catch",
                "next": "done",
            },
            "inner": {
                "type": "try_catch",
                "params": {},
                "body": "bad",
                "catch": "inner_catch",
                "next": None,
            },
            "bad": {"type": "stub", "params": {}, "next": None},
            "inner_catch": {"type": "stub", "params": {}, "next": None},
            "outer_catch": {"type": "stub", "params": {}, "next": None},
            "done": {"type": "stub", "params": {}, "next": None},
        },
    }
    with patch(
        "backend.core.interpreter.get_handler",
        side_effect=lambda t: _handlers(order, boom_ids={"bad"}),
    ):
        ctx = FlowInterpreter()._execute(flow)
    assert "inner_catch" in order
    assert "outer_catch" not in order
    assert order[-1] == "done"
    assert ctx.get("inner.raised") is True
    assert ctx.get("outer.raised") is False
