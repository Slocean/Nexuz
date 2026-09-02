"""AI 进度事件合帧（阶段3）：delta 合帧保序、process 瘦身、队列溢出告警。

验收标准（计划 M3）：模拟 5000 token 长输出 —— 前端可完整渲染（无丢字）、
事件总量 < 200 条。
"""

from __future__ import annotations

import threading

import pytest

from backend.api import Api


@pytest.fixture
def api(log_stub) -> Api:
    """最小事件总线实例（不走 __init__，不启窗口/线程）。"""
    a = Api.__new__(Api)
    a._emit_lock = threading.RLock()
    a._emit_queue = []
    a._emit_stop = threading.Event()
    a._emit_wake = threading.Event()
    a._ai_delta_lock = threading.Lock()
    a._ai_delta_bufs = {}
    a._dropped_events_total = 0
    return a


@pytest.fixture
def log_stub(monkeypatch):
    """队列溢出时的告警日志打桩，避免污染真实日志目录。"""
    rows: list[dict] = []

    class _Stub:
        def write_row(self, row, **kwargs):
            rows.append(row)

    monkeypatch.setattr("backend.api.get_app_log_manager", lambda: _Stub())
    return rows


def _delta(api: Api, text: str, *, cid="c1", aid="a1", typ="delta", **extra):
    api._queue_ai_progress({"type": typ, "conversation_id": cid, "assistant_id": aid, "text": text, **extra})


def _drain(api: Api):
    return api.drain_ui_events()["messages"]


def test_5000_token_output_coalesced_and_lossless(api):
    """验收：5000 token → 事件量 < 200，文本完整无丢字。"""
    tokens = [f"词{i}，" for i in range(5000)]
    for t in tokens:
        _delta(api, t)
    events = [m["payload"] for m in _drain(api) if m["payload"].get("type") == "delta"]
    assert len(events) < 200
    joined = "".join(e["text"] for e in events)
    assert joined == "".join(tokens)


def test_drain_flushes_pending_deltas(api):
    """两次 drain 之间累积的 delta 合并为一条（延迟 ≤ 一个轮询间隔）。"""
    _delta(api, "hello ")
    _delta(api, "world")
    events = _drain(api)
    assert len(events) == 1
    assert events[0]["payload"]["text"] == "hello world"


def test_process_event_slimmed_no_full_snapshot(api):
    """process 事件去掉全量 process 快照，只保留 step（前端累积）。"""
    api._queue_ai_progress(
        {
            "type": "process",
            "conversation_id": "c1",
            "assistant_id": "a1",
            "step": {"kind": "info", "label": "s1"},
            "process": [{"kind": "info", "label": "s1"}, {"kind": "info", "label": "s2"}],
        }
    )
    events = _drain(api)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert "process" not in payload
    assert payload["step"]["label"] == "s1"


def test_done_flushes_pending_deltas_in_order(api):
    """done 事件先冲刷缓冲：前端收到的 delta 一定先于 done。"""
    _delta(api, "part1-")
    _delta(api, "part2")
    api._queue_ai_progress(
        {"type": "done", "conversation_id": "c1", "assistant_id": "a1"}
    )
    events = _drain(api)
    types = [m["payload"]["type"] for m in events]
    assert types == ["delta", "done"]
    assert events[0]["payload"]["text"] == "part1-part2"


def test_replace_delta_not_merged(api):
    """replace 语义（非流式兜底）必须独立成事件，且先冲掉已有增量。"""
    _delta(api, "partial")
    _delta(api, "完整内容", replace=True)
    events = [m["payload"] for m in _drain(api)]
    assert len(events) == 2
    assert events[0]["text"] == "partial"
    assert events[1]["text"] == "完整内容" and events[1]["replace"] is True


def test_reasoning_and_delta_buffered_separately(api):
    """delta 与 reasoning 各自按 type 分桶，互不串字。"""
    _delta(api, "answer", typ="delta")
    _delta(api, "thinking", typ="reasoning")
    events = sorted((m["payload"] for m in _drain(api)), key=lambda p: p["type"])
    assert [e["text"] for e in events] == ["answer", "thinking"]


def test_multiple_conversations_isolated(api):
    _delta(api, "a", cid="c1")
    _delta(api, "b", cid="c2")
    events = _drain(api)
    assert len(events) == 2
    assert {e["payload"]["conversation_id"] for e in events} == {"c1", "c2"}


def test_overflow_drops_oldest_and_logs(api, log_stub):
    """队列触顶：丢最老一半 + 记 warning 日志（不再静默）。"""
    for i in range(600):
        api._queue_ui_event({"event": "noop", "payload": {"i": i}})
    assert api._dropped_events_total == 250
    assert len(api._emit_queue) == 350  # 600 - 250
    assert any("溢出" in str(r.get("message") or "") for r in log_stub)
    # 最老的 250 条被丢
    assert api._emit_queue[0]["payload"]["i"] == 250


def test_char_cap_triggers_midstream_flush(api):
    """超大缓冲（≥2048 字符）主动冲刷，内存有界。"""
    big = "x" * 3000
    _delta(api, big)
    assert not api._ai_delta_bufs  # 已主动冲刷
    events = _drain(api)
    assert len(events) == 1 and events[0]["payload"]["text"] == big
