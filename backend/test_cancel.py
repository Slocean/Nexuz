"""阶段2可靠性：AI 轮次取消（TurnCancelled / 检查点 / 注册表）+ 超时执行。"""

from __future__ import annotations

import threading
import time

import pytest

from backend.core.ai import cancel as tc


def test_turn_registry_lifecycle():
    assert tc.stop_turn("c1") is False  # 无进行中轮次
    tc.start_turn("c1")
    assert tc.is_cancelled("c1") is False
    assert tc.stop_turn("c1") is True
    assert tc.is_cancelled("c1") is True
    tc.finish_turn("c1")
    assert tc.is_cancelled("c1") is False
    assert tc.stop_turn("c1") is False  # 注销后不可再停


def test_checkpoint_raises_only_when_cancelled():
    tc.start_turn("c2")
    tc.checkpoint("c2")  # 未取消 → 不抛
    tc.stop_turn("c2")
    with pytest.raises(tc.TurnCancelled):
        tc.checkpoint("c2")
    tc.finish_turn("c2")
    tc.checkpoint("c2")  # 已注销视为未取消


def test_turn_cancelled_bypasses_except_exception():
    """TurnCancelled 继承 BaseException：链路上的 except Exception 不得吞掉它。"""
    tc.start_turn("c3")
    tc.stop_turn("c3")

    def fake_llm_chain():
        try:
            tc.checkpoint("c3")
        except Exception:  # noqa: BLE001 - 这正是要防范的吞异常模式
            return {"ok": False, "error": "被吞了"}
        return {"ok": True}

    with pytest.raises(tc.TurnCancelled):
        fake_llm_chain()
    tc.finish_turn("c3")


def test_run_with_timeout_returns_result():
    finished, result = tc.run_with_timeout(lambda: 42, timeout_s=2.0)
    assert finished is True and result == 42


def test_run_with_timeout_reraises():
    def boom():
        raise ValueError("bad params")

    with pytest.raises(ValueError):
        tc.run_with_timeout(boom, timeout_s=2.0)


def test_run_with_timeout_times_out():
    release = threading.Event()

    def slow():
        release.wait(timeout=5.0)
        return "late"

    t0 = time.monotonic()
    finished, result = tc.run_with_timeout(slow, timeout_s=0.3)
    elapsed = time.monotonic() - t0
    assert finished is False and result is None
    assert elapsed < 2.0
    release.set()


def test_run_block_timeout_and_should_stop():
    """卡死的 handler：run_block 按超时返回 timed_out，should_stop 被置位。"""
    from backend.core.registry import BLOCK_REGISTRY, register_block
    from backend.core.ai import run_block as rb

    seen_stop = {"value": None}

    def stuck_handler(params, context, *, should_stop=None, **kwargs):
        seen_stop["value"] = should_stop
        for _ in range(100):
            if should_stop and should_stop():
                return {"stopped": True}
            time.sleep(0.05)
        return {"out": "never"}

    register_block(
        {
            "type": "fake_stuck",
            "label": "卡住",
            "category": "识别类",
            "inputs": [],
            "outputs": [],
        },
        stuck_handler,
    )
    try:
        rb.RUN_BLOCK_SAFE = frozenset(rb.RUN_BLOCK_SAFE | {"fake_stuck"})
        res = rb.run_block_once(
            {"type": "fake_stuck", "params": {}},
            run_ctx={"context": {}, "counter": 0},
            allow_run_block=True,
            allow_dangerous=False,
            timeout_s=0.4,
        )
        assert res["ok"] is False and res.get("timed_out") is True
        assert "超时" in res["error"]
        # 弃置线程收到 should_stop 置位信号
        deadline = time.monotonic() + 2.0
        while seen_stop["value"] is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert seen_stop["value"] is not None and seen_stop["value"]() is True
    finally:
        BLOCK_REGISTRY.pop("fake_stuck", None)
        rb.RUN_BLOCK_SAFE = frozenset(rb.RUN_BLOCK_SAFE - {"fake_stuck"})


def test_run_block_clamps_wait_blocks():
    """wait 类积木时长钳制：超上限 / <=0（无限等待）一律收口。"""
    from backend.core.ai.run_block import _clamp_wait

    p = {"timeout_ms": 999_999}
    _clamp_wait("wait_until", p)
    assert p["timeout_ms"] == 60_000

    p = {"timeout_ms": 0}  # wait_until 语义中 0 = 无限等待
    _clamp_wait("wait_until", p)
    assert p["timeout_ms"] == 60_000

    p = {"timeout_sec": 500}
    _clamp_wait("window_wait", p)
    assert p["timeout_sec"] == 60.0

    p = {"ms": 1000}
    _clamp_wait("delay", p)
    assert p["ms"] == 1000  # 未超上限不动


def test_refine_timeout_keeps_original_params():
    """ai_refine 超时 → 返回 None（保留原参数），不阻塞执行热路径。"""
    from backend.core.ai.node_refine import refine_node_params
    from backend.core.ai.types import AiConfig
    from backend.core.registry import BLOCK_REGISTRY, register_block

    if "fake_probe" not in BLOCK_REGISTRY:
        register_block(
            {
                "type": "fake_probe",
                "label": "探测",
                "category": "识别类",
                "inputs": [],
                "outputs": [],
            },
            lambda params, context, **kwargs: {},
        )

    def slow_invoke(*args, **kwargs):
        time.sleep(2.0)

    res = refine_node_params(
        "fake_probe",
        {"x": 1},
        {},
        cfg=AiConfig(enabled=True, base_url="https://api.example.com/v1"),
        invoke_fn=slow_invoke,
        timeout_s=0.3,
    )
    assert res is None
