"""解释器控制流主干：loop_n/foreach/while/forever、if/switch、
try_catch 三态状态机、异常路由与 finally 重抛、嵌套 try、force_reset 代际隔离。
"""

from __future__ import annotations

import time

import pytest

from backend.core.interpreter import FlowInterpreter
from backend.core.registry import BLOCK_REGISTRY, register_all_blocks, register_block


@pytest.fixture(autouse=True)
def _full_registry():
    register_all_blocks()


@pytest.fixture
def boom_block():
    def failing_handler(params, context, **kwargs):
        raise RuntimeError("boom-123")

    register_block({"type": "boom", "label": "必失败", "category": "测试"}, failing_handler)
    yield "boom"
    BLOCK_REGISTRY.pop("boom", None)


def _mark(var, value, nxt=None):
    """assign 节点：把 {value} 包装写入 $var（与 assign 既有语义一致）。"""
    node: dict = {"type": "assign", "params": {"mappings": {var: {"value": value}}}}
    if nxt:
        node["next"] = nxt
    return node


def _run(flow, events=None):
    cb = (lambda event, payload: events.append((event, payload))) if events is not None else None
    return FlowInterpreter(cb)._execute(flow)


def _starts(events, node_id):
    return [p for e, p in events if e == "node_start" and p.get("node_id") == node_id]


# --- loop_n -----------------------------------------------------------------


def test_loop_n_runs_exact_times_and_resets_counter():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {"type": "loop_n", "params": {"times": 3}, "body": "b", "next": "after"},
            "b": _mark("t", 1),  # 无 next → fallthrough 回循环头
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 3
    assert len(_starts(events, "after")) == 1
    assert context["__loop_L1__counter"] == 0  # 退出后计数器归零（可复跑）
    assert context["$done"] == {"value": True}


def test_loop_n_zero_times_skips_body():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {"type": "loop_n", "params": {"times": 0}, "body": "b", "next": "after"},
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 0
    assert context["$done"] == {"value": True}


def test_loop_n_missing_body_raises():
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {"L1": {"type": "loop_n", "params": {"times": 2}}},
    }
    with pytest.raises(ValueError, match="缺少 body"):
        _run(flow)


# --- loop_foreach -----------------------------------------------------------


def test_loop_foreach_iterates_items_and_exposes_item():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {
                "type": "loop_foreach",
                "params": {"collection": ["a", "b", "c"], "item_var": "it"},
                "body": "b",
                "next": "after",
            },
            "b": _mark("got", "{{it}}"),  # 无 next → fallthrough 回循环头
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 3
    assert context["it"] == "c"  # 最后一轮注入的元素
    assert context["$got"] == {"value": "c"}
    assert context["__loop_L1__counter"] == 0
    assert context["$done"] == {"value": True}


def test_loop_foreach_empty_collection_runs_nothing():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {"type": "loop_foreach", "params": {"collection": []}, "body": "b", "next": "after"},
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 0
    assert context["$done"] == {"value": True}


# --- loop_while / loop_forever -----------------------------------------------


def test_loop_while_false_condition_runs_zero_times():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {"type": "loop_while", "params": {"expression": "1 == 2"}, "body": "b", "next": "after"},
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 0
    assert context["$done"] == {"value": True}


def test_loop_while_max_times_boundary():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {
                "type": "loop_while",
                "params": {"expression": "1 == 1", "max_times": 3},
                "body": "b",
                "next": "after",
            },
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 3  # max_times 是硬上界
    assert context["__loop_L1__counter"] == 0
    assert context["$done"] == {"value": True}


def test_loop_forever_exit_condition_checked_before_first_body():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {
                "type": "loop_forever",
                "params": {"exit_condition": "1 == 1"},
                "body": "b",
                "next": "after",
            },
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 0
    assert context["$done"] == {"value": True}


def test_loop_forever_max_times_boundary():
    events: list = []
    flow = {
        "entry": "L1",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "L1": {"type": "loop_forever", "params": {"max_times": 2}, "body": "b", "next": "after"},
            "b": _mark("t", 1),
            "after": _mark("done", True),
        },
    }
    context = _run(flow, events)
    assert len(_starts(events, "b")) == 2
    assert context["__loop_L1__counter"] == 0
    assert context["$done"] == {"value": True}


# --- if / switch --------------------------------------------------------------


def test_if_condition_routes_then_and_else():
    def make(expression):
        return {
            "entry": "IF",
            "execution_policy": {"mode": "safe"},
            "nodes": {
                "IF": {
                    "type": "if_condition",
                    "params": {"expression": expression},
                    "then": "t",
                    "else": "e",
                    "next": "after",
                },
                "t": _mark("branch", "then", "after"),
                "e": _mark("branch", "else", "after"),
                "after": _mark("done", True),
            },
        }

    context = _run(make("1 == 1"))
    assert context["$branch"] == {"value": "then"}
    context = _run(make("1 == 2"))
    assert context["$branch"] == {"value": "else"}


def test_switch_matches_case_and_default():
    def make(mode):
        return {
            "entry": "init",
            "execution_policy": {"mode": "safe"},
            "nodes": {
                "init": _mark("mode", mode, "SW"),
                "SW": {
                    "type": "switch",
                    "params": {
                        "variable": "{{mode.value}}",
                        "cases": [
                            {"value": "a", "node_id": "na"},
                            {"value": "b", "node_id": "nb"},
                        ],
                        "default": "nd",
                    },
                },
                "na": _mark("hit", "na"),
                "nb": _mark("hit", "nb"),
                "nd": _mark("hit", "default"),
            },
        }

    context = _run(make("b"))
    assert context["$hit"] == {"value": "nb"}
    context = _run(make("zzz"))
    assert context["$hit"] == {"value": "default"}


# --- try_catch 三态 / 异常路由 / 重抛 ----------------------------------------


def test_try_catch_body_error_routes_to_catch_then_continues(boom_block):
    events: list = []
    flow = {
        "entry": "T",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "T": {"type": "try_catch", "body": "tb", "catch": "tc", "next": "after"},
            "tb": {"type": "boom"},  # body 失败 → 路由到 catch
            "tc": _mark("caught", True),  # 无 next → 回 T（catch 完成）
            "after": _mark("after", True),
        },
    }
    context = _run(flow, events)
    assert context["$caught"] == {"value": True}
    assert context["T.raised"] is True
    assert "boom-123" in str(context["T.error"])
    assert context["$after"] == {"value": True}  # catch 吞掉异常后流程继续
    assert len(_starts(events, "after")) == 1


def test_try_catch_clean_body_skips_catch_runs_finally():
    events: list = []
    flow = {
        "entry": "T",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "T": {"type": "try_catch", "body": "tb", "catch": "tc", "finally": "tf", "next": "after"},
            "tb": _mark("ok", True),
            "tc": _mark("caught", True),
            "tf": _mark("fin", True),
            "after": _mark("after", True),
        },
    }
    context = _run(flow, events)
    assert context["$ok"] == {"value": True}
    assert context["$fin"] == {"value": True}  # finally 总是执行
    assert "caught" not in context  # catch 未执行
    assert context["T.raised"] is False
    assert context["$after"] == {"value": True}


def test_try_catch_finally_without_catch_reraises(boom_block):
    """body 失败 + 只有 finally：finally 执行后异常必须重抛（__pending_reraise__ 路径）。"""
    events: list = []
    flow = {
        "entry": "T",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "T": {"type": "try_catch", "body": "tb", "finally": "tf", "next": "after"},
            "tb": {"type": "boom"},  # 失败且无 catch → finally 后重抛
            "tf": _mark("fin", True),
            "after": _mark("after", True),
        },
    }
    with pytest.raises(RuntimeError, match="boom-123"):
        _run(flow, events)
    assert len(_starts(events, "tf")) == 1  # finally 先执行
    assert len(_starts(events, "after")) == 0  # 异常重抛，next 不执行


def test_nested_try_inner_reraise_caught_by_outer(boom_block):
    """内层 try 只有 finally → 重抛；外层 catch 接住。"""
    flow = {
        "entry": "T2",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "T2": {"type": "try_catch", "body": "t2_body", "catch": "t2_catch", "next": "after"},
            "t2_body": {"type": "try_catch", "body": "t1_body", "finally": "t1_fin", "next": "after"},
            "t1_body": {"type": "boom"},  # 内层失败且无 catch → 重抛
            "t1_fin": _mark("inner_fin", True),
            "t2_catch": _mark("outer_caught", True),
            "after": _mark("after", True),
        },
    }
    context = _run(flow)
    assert context["$inner_fin"] == {"value": True}  # 内层 finally 先执行
    assert context["$outer_caught"] == {"value": True}  # 重抛被外层 catch 接住
    assert context["T2.raised"] is True
    assert context["$after"] == {"value": True}


def test_try_catch_error_message_recorded(boom_block):
    flow = {
        "entry": "T",
        "execution_policy": {"mode": "safe"},
        "nodes": {
            "T": {"type": "try_catch", "body": "tb", "catch": "tc"},
            "tb": {"type": "boom"},
            "tc": _mark("caught", True),
        },
    }
    context = _run(flow)
    assert context["T.raised"] is True
    assert context["T.error"] == "boom-123"


# --- force_reset 代际隔离 ------------------------------------------------------


def test_force_reset_orphans_run_and_frees_interpreter():
    events: list = []
    interp = FlowInterpreter(lambda e, p: events.append((e, p)))
    long_flow = {
        "name": "long",
        "entry": "w",
        "execution_policy": {"mode": "safe"},
        "nodes": {"w": {"type": "delay", "params": {"ms": 5000}}},
    }
    assert interp.run_flow(long_flow).get("started") is True
    assert interp.running is True

    time.sleep(0.2)
    result = interp.force_reset()
    assert result.get("had_run") is True
    assert interp.running is False  # 立即可再跑（旧线程被弃置为孤儿）

    short_flow = {
        "entry": "a",
        "execution_policy": {"mode": "safe"},
        "nodes": {"a": _mark("ok2", True)},
    }
    assert interp.run_flow(short_flow).get("started") is True
    interp.wait_until_idle(timeout=5.0)
    assert interp.running is False

    finished = [p for e, p in events if e == "flow_finished"]
    assert any(p.get("forced") for p in finished)  # 旧代收到 forced 事件
    # 新代跑完：孤儿线程（run_id 已过期）不得覆盖新代状态
    assert interp.running is False
