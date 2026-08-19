from __future__ import annotations

import pytest

from backend.blocks.assign import handler as assign_handler
from backend.core.interpreter import FlowInterpreter, node_pre_delay_ms
from backend.core.registry import BLOCK_REGISTRY, register_all_blocks, register_block


@pytest.fixture
def isolated_registry():
    previous = dict(BLOCK_REGISTRY)
    BLOCK_REGISTRY.clear()
    register_block({"type": "assign"}, assign_handler)
    yield
    BLOCK_REGISTRY.clear()
    BLOCK_REGISTRY.update(previous)


def test_variable_binding_is_resolved_between_nodes(isolated_registry):
    flow = {
        "entry": "source",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "source": {
                "type": "assign",
                "params": {"mappings": {"source": {"value": 7}}},
                "next": "target",
            },
            "target": {
                "type": "assign",
                "params": {"mappings": {"copied": "{{source}}"}},
            },
        },
    }

    context = FlowInterpreter()._execute(flow)
    assert context["$copied"] == {"value": 7}


def test_disabled_unknown_node_is_skipped(isolated_registry):
    events = []
    flow = {
        "entry": "disabled",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "disabled": {
                "type": "not_registered",
                "disabled": True,
                "next": "done",
            },
            "done": {
                "type": "assign",
                "params": {"mappings": {"finished": True}},
            },
        },
    }

    context = FlowInterpreter(lambda event, payload: events.append((event, payload)))._execute(flow)
    assert context["$finished"] is True
    assert any(event == "node_end" and payload.get("skipped") for event, payload in events)


def test_handler_failure_emits_failed_node_event(isolated_registry):
    def failing_handler(params, context, **kwargs):
        raise RuntimeError("expected failure")

    register_block({"type": "failing"}, failing_handler)
    events = []
    flow = {
        "entry": "fail",
        "execution_policy": {"mode": "safe"},
        "nodes": {"fail": {"type": "failing", "params": {}}},
    }

    with pytest.raises(RuntimeError, match="expected failure"):
        FlowInterpreter(lambda event, payload: events.append((event, payload)))._execute(flow)

    failed = [payload for event, payload in events if event == "node_end"]
    assert failed[-1]["ok"] is False
    assert failed[-1]["error"] == "expected failure"


def test_node_pre_delay_respects_first_node_and_explicit_override():
    assert node_pre_delay_ms(0, None, 250) == 0
    assert node_pre_delay_ms(1, None, 250) == 250
    assert node_pre_delay_ms(0, 100, 250) == 100
    assert node_pre_delay_ms(2, "invalid", 250) == 0


def test_builtin_registry_smoke_has_complete_schema_and_handlers():
    registry = register_all_blocks()
    assert len(registry) >= 35
    for block_type, entry in registry.items():
        assert entry["schema"]["type"] == block_type
        assert callable(entry["handler"])
