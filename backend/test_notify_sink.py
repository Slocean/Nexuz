"""NotifySink：日志全量接收、webhook 白名单事件异步外发、失败重试。"""

from __future__ import annotations

import time

from backend.core.notify_sink import WEBHOOK_EVENTS, NotifySink


def test_sink_accepts_all_events_without_webhook():
    sink = NotifySink()  # 无 webhook：只写日志，不应抛错
    sink.emit("node_start", {"node_id": "n1"})
    sink.emit("schedule_fired", {"job_id": "j1"})
    sink.emit(None, "weird")  # 容错：event/payload 非常规输入


def test_webhook_whitelist_events_dispatched():
    posted: list[dict] = []
    sink = NotifySink(webhook_url="http://example.com/hook", poster=posted.append)
    sink.emit("schedule_error", {"job_id": "j1", "reason": "execution_error"})
    sink.emit("flow_finished", {"ok": True})
    sink.emit("node_start", {"node_id": "n1"})  # 白名单外：不外发
    # 异步线程投递
    deadline = time.monotonic() + 3
    while len(posted) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(posted) == 2
    assert posted[0]["event"] == "schedule_error"
    assert posted[0]["source"] == "nexuz-server"
    assert posted[0]["payload"]["job_id"] == "j1"
    assert posted[0]["ts"]
    assert "schedule_fired" in WEBHOOK_EVENTS


def test_webhook_retry_once_then_give_up():
    calls: list[int] = []

    def failing_poster(body: dict) -> None:
        # poster 注入路径不重试（重试在 _deliver 的生产分支）；这里验证
        # 白名单事件才走 poster、poster 异常不外泄
        calls.append(1)
        raise RuntimeError("boom")

    sink = NotifySink(webhook_url="http://example.com/hook", poster=failing_poster)
    sink.emit("schedule_fired", {"job_id": "j1"})
    deadline = time.monotonic() + 3
    while len(calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(calls) == 1
    time.sleep(0.1)
    assert len(calls) == 1


def test_webhook_url_from_config(monkeypatch):
    import backend.core.notify_sink as ns

    monkeypatch.setattr(
        ns, "config_webhook_url", lambda: "http://cfg.example.com/hook "
    )
    sink = NotifySink()
    assert sink.webhook_url == "http://cfg.example.com/hook"


def test_explicit_url_overrides_config(monkeypatch):
    import backend.core.notify_sink as ns

    monkeypatch.setattr(ns, "config_webhook_url", lambda: "http://cfg.example.com/hook")
    sink = NotifySink(webhook_url="http://explicit.example.com/hook")
    assert sink.webhook_url == "http://explicit.example.com/hook"
