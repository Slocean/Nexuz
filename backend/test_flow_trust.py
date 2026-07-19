"""Regression checks for external-flow capability previews."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.flow_trust import analyze_flow_risks


def test_low_risk_flow() -> None:
    result = analyze_flow_risks(
        {"nodes": {"a": {"type": "click"}, "b": {"type": "delay"}}},
        known_types={"click", "delay"},
    )
    assert result["needs_strong_warning"] is False
    assert result["capabilities"] == []
    assert result["unknown_types"] == []


def test_high_risk_and_unknown_blocks() -> None:
    result = analyze_flow_risks(
        {
            "nodes": {
                "a": {"type": "python_script"},
                "b": {"type": "run_command"},
                "c": {"type": "run_command"},
                "d": {"type": "third_party_plugin"},
                "e": {"type": "my_plugin"},
            }
        },
        known_types={"python_script", "run_command", "my_plugin"},
        trusted_plugin_types={"my_plugin"},
    )
    assert result["needs_strong_warning"] is True
    counts = {item["type"]: item["count"] for item in result["capabilities"]}
    assert counts == {"my_plugin": 1, "python_script": 1, "run_command": 2}
    assert result["unknown_types"] == [{"type": "third_party_plugin", "count": 1}]


if __name__ == "__main__":
    test_low_risk_flow()
    test_high_risk_and_unknown_blocks()
    print("FLOW TRUST OK")
