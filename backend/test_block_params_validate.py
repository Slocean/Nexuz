from __future__ import annotations

import pytest

from backend.core.block_params_validate import validate_flow_params
from backend.core.registry import BLOCK_REGISTRY, register_block


@pytest.fixture(autouse=True)
def isolated_registry():
    previous = dict(BLOCK_REGISTRY)
    BLOCK_REGISTRY.clear()
    register_block(
        {
            "type": "demo",
            "inputs": [
                {"name": "count", "label": "次数", "type": "number", "required": True},
                {
                    "name": "mode",
                    "label": "模式",
                    "type": "select",
                    "options": ["fast", "safe"],
                    "default": "safe",
                },
                {"name": "options", "label": "选项", "type": "object", "default": {}},
            ],
        },
        lambda *_args, **_kwargs: {},
    )
    yield
    BLOCK_REGISTRY.clear()
    BLOCK_REGISTRY.update(previous)


def test_valid_literals_and_binding_are_accepted():
    flow = {
        "nodes": {
            "literal": {
                "type": "demo",
                "params": {"count": "3", "mode": "fast", "options": {}},
            },
            "binding": {
                "type": "demo",
                "params": {"count": "{{source.value}}", "mode": "safe"},
            },
        }
    }
    assert validate_flow_params(flow) == []


def test_required_type_enum_and_unknown_block_are_structured():
    flow = {
        "nodes": {
            "missing": {"type": "demo", "params": {"mode": "invalid"}},
            "bad_type": {"type": "demo", "params": {"count": "many", "options": []}},
            "unknown": {"type": "missing_block", "params": {}},
        }
    }
    issues = validate_flow_params(flow)
    assert {issue["code"] for issue in issues} == {
        "required",
        "enum",
        "type",
        "unknown_block",
    }
    assert all("node_id" in issue and "block_type" in issue for issue in issues)


def test_disabled_invalid_node_is_ignored():
    flow = {
        "nodes": {
            "disabled": {
                "type": "missing_block",
                "params": {},
                "disabled": True,
            }
        }
    }
    assert validate_flow_params(flow) == []
