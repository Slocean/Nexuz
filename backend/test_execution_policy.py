from __future__ import annotations

import pytest

from backend.blocks.assign import handler as assign_handler
from backend.blocks.if_condition import handler as if_handler
from backend.core.execution_policy import (
    ExecutionPolicyError,
    check_node_allowed,
    resolve_execution_policy,
    scan_flow_violations,
)
from backend.core.interpreter import FlowInterpreter
from backend.core.registry import BLOCK_REGISTRY, register_block


@pytest.fixture(autouse=True)
def isolated_registry():
    previous = dict(BLOCK_REGISTRY)
    BLOCK_REGISTRY.clear()
    register_block({"type": "assign"}, assign_handler)
    register_block({"type": "if_condition"}, if_handler)
    yield
    BLOCK_REGISTRY.clear()
    BLOCK_REGISTRY.update(previous)


def test_safe_policy_blocks_dangerous_handler_before_execution():
    called = False

    def dangerous_handler(params, context, **kwargs):
        nonlocal called
        called = True
        return {}

    register_block({"type": "run_command"}, dangerous_handler)
    flow = {
        "entry": "cmd",
        "nodes": {"cmd": {"type": "run_command", "params": {"command": "whoami"}}},
        "execution_policy": {"mode": "safe"},
    }

    with pytest.raises(ExecutionPolicyError) as exc_info:
        FlowInterpreter()._execute(flow)

    assert called is False
    assert exc_info.value.violation["block_type"] == "run_command"


def test_legacy_flow_keeps_existing_behavior():
    called = False

    def dangerous_handler(params, context, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    register_block({"type": "run_command"}, dangerous_handler)
    flow = {
        "entry": "cmd",
        "nodes": {"cmd": {"type": "run_command", "params": {}}},
    }

    FlowInterpreter()._execute(flow)
    assert called is True
    assert resolve_execution_policy(flow).mode == "legacy"


def test_safe_policy_allows_control_flow_and_selects_then_branch():
    flow = {
        "entry": "set",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "set": {
                "type": "assign",
                "params": {"mappings": {"answer": 42}},
                "next": "check",
            },
            "check": {
                "type": "if_condition",
                "params": {"expression": "$answer == 42"},
                "then": "yes",
                "else": "no",
            },
            "yes": {
                "type": "assign",
                "params": {"mappings": {"passed": True}},
            },
            "no": {
                "type": "assign",
                "params": {"mappings": {"passed": False}},
            },
        },
    }

    context = FlowInterpreter()._execute(flow)
    assert context["$passed"] is True


def test_scan_reports_frida_and_file_access_but_skips_disabled_nodes():
    flow = {
        "entry": "click",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "click": {
                "type": "click",
                "params": {"capture_mode": "frida_ui"},
                "next": "file",
            },
            "file": {"type": "file_io", "params": {}, "next": "disabled"},
            "disabled": {
                "type": "python_script",
                "params": {},
                "disabled": True,
            },
        },
    }

    violations = scan_flow_violations(flow)
    assert [item["block_type"] for item in violations] == ["click", "file_io"]


# ---- MCP 策略下限（__policy_floor__）----


def _floor_policy(flow: dict):
    from backend.core.execution_policy import apply_policy_floor, mcp_policy_floor

    return apply_policy_floor(resolve_execution_policy(flow), mcp_policy_floor())


def test_floor_lifts_legacy_and_denies_critical():
    policy = _floor_policy({})
    assert policy.mode == "standard"
    for t in ("python_script", "run_command", "power_action"):
        assert t in policy.denylist
        assert check_node_allowed(policy, "n", {"type": t}) is not None
    # elevated 正常放行
    assert check_node_allowed(policy, "n", {"type": "http_request"}) is None


def test_floor_keeps_safe_mode_restrictions():
    policy = _floor_policy({"execution_policy": {"mode": "safe"}})
    assert policy.mode == "safe"
    # safe 模式自身拦截 elevated，下限不得放松
    assert check_node_allowed(policy, "n", {"type": "http_request"}) is not None
    assert check_node_allowed(policy, "n", {"type": "python_script"}) is not None


def test_floor_noop_without_marker():
    from backend.core.execution_policy import apply_policy_floor

    base = resolve_execution_policy({"execution_policy": {"mode": "standard"}})
    assert apply_policy_floor(base, None) is base
    assert apply_policy_floor(base, {}) is base


def test_flow_cannot_weaken_floor():
    # 流程自带 execution_policy 无法削弱下限：deny 取并集、mode 只升不降
    policy = _floor_policy({"execution_policy": {"mode": "legacy"}})
    assert policy.mode == "standard"
    assert "python_script" in policy.denylist


def test_floor_scan_rejects_inline_critical_flow():
    flow = {
        "entry": "n1",
        "nodes": {"n1": {"type": "python_script", "params": {}}},
    }
    violations = scan_flow_violations(flow, _floor_policy(flow))
    assert [item["block_type"] for item in violations] == ["python_script"]
