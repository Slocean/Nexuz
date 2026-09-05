"""监控积木与 MonitorManager：边沿事件、长轮询唤醒、增量游标、过期、恢复。"""

from __future__ import annotations

import time

import pytest

from backend.core import monitor as monitor_mod
from backend.core.monitor import MonitorManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_mod, "_monitors_file", lambda: tmp_path / "monitors.json")
    manager = MonitorManager()
    yield manager
    manager.stop_all()


def _file_spec(path, *, on="appear", **over):
    spec = {
        "monitor_type": "file",
        "params": {"file_path": str(path), "on": on},
        "poll_interval_ms": 100,
        "expire_seconds": 0,
    }
    spec.update(over)
    return spec


def test_file_appear_wakes_waiter(mgr, tmp_path):
    target = tmp_path / "flag.txt"
    res = mgr.start_monitor(_file_spec(target), monitor_id="watch1")
    assert res["monitor_id"] == "watch1"

    r0 = mgr.wait_events("watch1", timeout_s=0.25)
    assert r0["got"] is False and r0["timed_out"] is True

    target.write_text("hello", encoding="utf-8")
    r1 = mgr.wait_events("watch1", timeout_s=5)
    assert r1["got"] is True and r1["count"] == 1
    event = r1["events"][0]
    assert event["type"] == "file" and event["fire"] == "edge"
    assert event["data"]["exists"] is True
    assert r1["last_event_id"] == event["id"] == 1

    r2 = mgr.drain_events("watch1", since_event_id=event["id"])
    assert r2["got"] is False and r2["last_event_id"] == 1
    r3 = mgr.wait_events("watch1", since_event_id=1, timeout_s=0.25)
    assert r3["got"] is False and r3["timed_out"] is True


def test_edge_only_fire_on_start_and_refire(mgr, tmp_path):
    target = tmp_path / "on.txt"
    target.write_text("v1", encoding="utf-8")

    mgr.start_monitor(_file_spec(target), monitor_id="m1")
    time.sleep(0.35)
    assert mgr.drain_events("m1")["got"] is False  # 启动即真：不翻转不记事件

    mgr.start_monitor(_file_spec(target, fire_on_start=True), monitor_id="m2")
    r = mgr.wait_events("m2", timeout_s=3)
    assert r["got"] is True and r["events"][0]["fire"] == "start"

    mgr.start_monitor(
        _file_spec(target, fire_on_start=True, refire_ms=150), monitor_id="m3"
    )
    first = mgr.wait_events("m3", timeout_s=3)
    assert first["got"] is True
    second = mgr.wait_events("m3", since_event_id=first["last_event_id"], timeout_s=3)
    assert second["got"] is True and second["events"][0]["fire"] == "refire"


def test_process_disappear_with_fire_on_start(mgr):
    spec = {
        "monitor_type": "process",
        "params": {"process_name": "definitely_not_running_zz.exe", "on": "disappear"},
        "poll_interval_ms": 100,
        "fire_on_start": True,
        "expire_seconds": 0,
    }
    mgr.start_monitor(spec, monitor_id="proc")
    r = mgr.wait_events("proc", timeout_s=8)
    assert r["got"] is True
    event = r["events"][0]
    assert event["fire"] == "start" and event["data"]["exists"] is False


def test_window_monitor_requires_criteria(mgr):
    with pytest.raises(ValueError):
        mgr.start_monitor({"monitor_type": "window", "params": {"on": "appear"}})


def test_wait_and_drain_missing_monitor(mgr):
    for res in (mgr.wait_events("ghost", timeout_s=0.1), mgr.drain_events("ghost")):
        assert res["got"] is False
        assert res["status"] == "missing"
        assert "不存在" in res["error"]


def test_expire_marks_status_and_wakes_waiter(mgr, tmp_path):
    mgr.start_monitor(_file_spec(tmp_path / "never.txt", expire_seconds=1), monitor_id="short")
    t0 = time.monotonic()
    r = mgr.wait_events("short", timeout_s=6)
    assert r["got"] is False
    assert r["status"] == "expired" and "过期" in r["error"]
    assert time.monotonic() - t0 < 6  # 过期即刻穿透等待，不等满超时


def test_stop_missing_and_replace_same_id(mgr, tmp_path):
    assert mgr.stop_monitor("ghost") is False
    mgr.start_monitor(_file_spec(tmp_path / "a.txt"), monitor_id="dup")
    assert mgr.stop_monitor("dup") is True
    assert mgr.drain_events("dup")["status"] == "missing"
    mgr.start_monitor(_file_spec(tmp_path / "b.txt"), monitor_id="dup")  # 同 id 替换
    statuses = mgr.list_monitors()
    assert len(statuses) == 1 and statuses[0]["status"] == "running"


def test_persist_and_restore_keeps_event_cursor(mgr, tmp_path):
    target = tmp_path / "keep.txt"
    # change + fire_on_start：无论首检发生在写入前(start)后(edge)，都必定记且只记一次。
    target.write_text("x", encoding="utf-8")
    mgr.start_monitor(_file_spec(target, on="change", fire_on_start=True), monitor_id="keep1")
    target.write_text("xx", encoding="utf-8")  # 1B → 2B
    r0 = mgr.wait_events("keep1", timeout_s=5)
    assert r0["got"] is True and r0["count"] == 1  # 消费 id=1，水位已持久化

    restored = MonitorManager()  # 同一路径（fixture 已 monkeypatch）
    try:
        assert restored.restore() == 1
        status = restored.get_status("keep1")
        assert status["status"] == "running" and status["last_event_id"] == 1
        target.write_text("xxx", encoding="utf-8")  # 2B → 3B
        deadline = time.monotonic() + 5
        event = None
        while time.monotonic() < deadline and event is None:
            got = restored.drain_events("keep1", since_event_id=1)
            if got["got"]:
                event = got["events"][0]
            else:
                time.sleep(0.05)
        assert event is not None and event["id"] >= 2  # id 水位接续，旧游标不漏事件
    finally:
        restored.stop_all()


def test_max_monitors_cap(mgr, tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_mod, "_MAX_MONITORS", 2)
    mgr.start_monitor(_file_spec(tmp_path / "1.txt"), monitor_id="c1")
    mgr.start_monitor(_file_spec(tmp_path / "2.txt"), monitor_id="c2")
    with pytest.raises(ValueError, match="上限"):
        mgr.start_monitor(_file_spec(tmp_path / "3.txt"), monitor_id="c3")
    mgr.start_monitor(_file_spec(tmp_path / "1b.txt"), monitor_id="c1")  # 替换不计入


def test_run_block_classification_and_wait_clamp():
    from backend.core.ai import run_block as rb

    for btype in ("monitor_start", "monitor_wait", "monitor_check", "monitor_stop", "monitor_list"):
        assert rb.classify_run_block(btype) == "safe"
    params = {"timeout_ms": 999999}
    rb._clamp_wait("monitor_wait", params)
    assert params["timeout_ms"] == 60_000.0
    params2 = {"timeout_ms": -5}
    rb._clamp_wait("monitor_wait", params2)
    assert params2["timeout_ms"] == 60_000.0


def test_schema_validation():
    from backend.blocks import monitor_start, monitor_stop, monitor_wait
    from backend.core.block_params_validate import validate_flow_params
    from backend.core.registry import BLOCK_REGISTRY, register_block

    for module in (monitor_start, monitor_wait, monitor_stop):
        register_block(module.SCHEMA, module.handler)
    try:
        issues = validate_flow_params(
            {
                "nodes": {
                    "a": {
                        "type": "monitor_start",
                        "params": {"monitor_type": "process", "process_name": "x.exe"},
                    }
                }
            }
        )
        assert [i for i in issues if i.get("level") == "error"] == []
        issues2 = validate_flow_params({"nodes": {"b": {"type": "monitor_wait", "params": {}}}})
        assert any(i.get("code") == "required" for i in issues2)
    finally:
        for module in (monitor_start, monitor_wait, monitor_stop):
            BLOCK_REGISTRY.pop(module.SCHEMA["type"], None)


def test_blocks_end_to_end_via_handlers(tmp_path, monkeypatch):
    from backend.blocks import monitor_check, monitor_list, monitor_start, monitor_stop, monitor_wait

    monkeypatch.setattr(monitor_mod, "_monitors_file", lambda: tmp_path / "monitors.json")
    res = monitor_start.handler(
        {
            "monitor_type": "process",
            "process_name": "no_such_zz.exe",
            "on": "disappear",
            "fire_on_start": "true",
            "poll_interval_ms": "200",
            "expire_seconds": "120",
            "toast": "false",
        },
        {},
    )
    assert res["started"] is True and res["monitor_id"]
    mid = res["monitor_id"]
    try:
        listed = monitor_list.handler({}, {})
        assert listed["count"] >= 1
        assert any(m["monitor_id"] == mid and "进程" in m["spec"] for m in listed["monitors"])

        w = monitor_wait.handler({"monitor_id": mid, "timeout_ms": "8000"}, {})
        assert w["got"] is True and "不存在" in w["events"][0]["detail"]

        c = monitor_check.handler({"monitor_id": mid, "since_event_id": w["last_event_id"]}, {})
        assert c["got"] is False
    finally:
        assert monitor_stop.handler({"monitor_id": mid}, {})["stopped"] is True
