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


# ---- __policy_floor__（外部 AI 执行下限）----


def _floor():
    return {
        "deny": ["python_script", "run_command", "power_action"],
        "mode_min": "standard",
    }


def test_policy_floor_denies_critical_node(isolated_registry):
    from backend.core.execution_policy import ExecutionPolicyError

    register_block({"type": "python_script"}, lambda params, context, **kwargs: {})
    flow = {
        "entry": "evil",
        # 无 execution_policy 字段（legacy），但下限标记强制拒绝危险命令类
        "__policy_floor__": _floor(),
        "nodes": {"evil": {"type": "python_script", "params": {}}},
    }

    # 逐节点闸在 handler 执行前拒绝（不产生 node_end 事件）
    with pytest.raises(ExecutionPolicyError):
        FlowInterpreter()._execute(flow)


def test_policy_floor_propagates_into_subflow(isolated_registry, tmp_path):
    import json

    from backend.blocks.call_subflow import handler as call_subflow_handler
    from backend.core.execution_policy import ExecutionPolicyError

    register_block({"type": "call_subflow"}, call_subflow_handler)
    register_block({"type": "python_script"}, lambda params, context, **kwargs: {})

    sub = tmp_path / "sub.flow.json"
    sub.write_text(
        json.dumps({"entry": "evil", "nodes": {"evil": {"type": "python_script", "params": {}}}}),
        encoding="utf-8",
    )
    flow = {
        "entry": "call",
        "__policy_floor__": _floor(),
        "nodes": {
            "call": {"type": "call_subflow", "params": {"subflow_path": str(sub)}},
        },
    }

    # 外层无危险积木，但下限随流程字典进入嵌套解释器，子流程内的
    # python_script 在逐节点闸被拒（handler 异常向上传播）
    with pytest.raises(ExecutionPolicyError):
        FlowInterpreter()._execute(flow)


def test_policy_floor_allows_normal_blocks(isolated_registry):
    flow = {
        "entry": "source",
        "__policy_floor__": _floor(),
        "nodes": {
            "source": {
                "type": "assign",
                "params": {"mappings": {"v": 1}},
            },
        },
    }
    context = FlowInterpreter()._execute(flow)
    assert context["$v"] == 1
