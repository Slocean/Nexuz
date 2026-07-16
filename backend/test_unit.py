"""Quick tests for expression + variable resolver."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.blocks._helpers import pre_step_delay_ms
from backend.core.expression import evaluate_expression
from backend.core.variable_resolver import resolve_variables


def test_variables():
    ctx = {"node_1.text": "登录成功", "$count": 3, "count": 3}
    params = {"msg": "{{node_1.text}}", "n": "$count", "mixed": "hi-{{node_1.text}}"}
    out = resolve_variables(params, ctx)
    assert out["msg"] == "登录成功"
    assert out["n"] == 3
    assert out["mixed"] == "hi-登录成功"


def test_expressions():
    ctx = {"node_1.text": "登录成功", "node_2.matched": True, "a": 5}
    assert evaluate_expression('{{node_1.text}} == "登录成功"', ctx) is True
    assert evaluate_expression('{{node_1.text}} contains "登录"', ctx) is True
    assert evaluate_expression("{{node_2.matched}}", ctx) is True
    assert evaluate_expression("{{a}} > 3", ctx) is True
    assert evaluate_expression('{{node_1.text}} != "x"', ctx) is True
    assert evaluate_expression('{{node_1.text}} == "x"', ctx) is False


def test_pre_step_delay_ms():
    # First step: empty → no wait; explicit delay honored (the old multi-click bug).
    assert pre_step_delay_ms(0, None, default_interval=200) == 0
    assert pre_step_delay_ms(0, "", default_interval=200) == 0
    assert pre_step_delay_ms(0, 1500, default_interval=200) == 1500
    assert pre_step_delay_ms(0, "3000", default_interval=200) == 3000
    assert pre_step_delay_ms(0, 0, default_interval=200) == 0
    # Later steps: empty falls back to global interval; explicit overrides.
    assert pre_step_delay_ms(1, None, default_interval=200) == 200
    assert pre_step_delay_ms(1, "", default_interval=200) == 200
    assert pre_step_delay_ms(1, 50, default_interval=200) == 50
    assert pre_step_delay_ms(2, 0, default_interval=200) == 0


if __name__ == "__main__":
    test_variables()
    test_expressions()
    test_pre_step_delay_ms()
    print("UNIT OK")
