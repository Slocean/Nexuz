from __future__ import annotations

import json

from backend.core.scheduler import FlowScheduler


class _FakeInterpreter:
    def __init__(self, running: bool):
        self.running = running
        self.started: list[dict] = []

    def run_flow(self, payload, step_mode=False):
        self.started.append(payload)
        self.running = True
        return {"started": True}


class _FakeRuntimeLogs:
    def start(self, payload):
        return None

    def finish(self, payload):
        return None


def test_busy_schedule_queues_once_then_persists_failure(tmp_path, monkeypatch):
    failures = tmp_path / "failures.jsonl"
    monkeypatch.setattr("backend.core.scheduler._failures_file", lambda: failures)
    interp = _FakeInterpreter(running=True)
    monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
    monkeypatch.setattr(
        "backend.core.runtime_log.get_runtime_log_manager",
        lambda: _FakeRuntimeLogs(),
    )
    events = []
    scheduler = FlowScheduler()
    scheduler._aps = None
    scheduler._jobs["job-1"] = {"trigger_type": "interval", "file_path": ""}
    scheduler.set_emit(lambda event, payload: events.append((event, payload)))

    scheduler._start_or_queue("job-1", {"entry": "a"}, scheduler._jobs["job-1"])
    scheduler._start_or_queue("job-1", {"entry": "a"}, scheduler._jobs["job-1"])

    status = scheduler.list_jobs()[0]
    assert status["pending"] is True
    assert status["last_failure"]["reason"] == "pending_full"
    row = json.loads(failures.read_text(encoding="utf-8").splitlines()[0])
    assert row["job_id"] == "job-1"
    assert [event for event, _ in events] == ["schedule_pending", "schedule_error"]


def test_pending_schedule_drains_when_interpreter_is_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.core.scheduler._failures_file",
        lambda: tmp_path / "failures.jsonl",
    )
    interp = _FakeInterpreter(running=True)
    monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
    monkeypatch.setattr(
        "backend.core.runtime_log.get_runtime_log_manager",
        lambda: _FakeRuntimeLogs(),
    )
    scheduler = FlowScheduler()
    scheduler._aps = None
    meta = {"trigger_type": "interval", "file_path": ""}
    scheduler._jobs["job-1"] = meta
    scheduler._start_or_queue("job-1", {"entry": "a"}, meta)

    interp.running = False
    scheduler._drain_pending_once()

    assert interp.started == [{"entry": "a"}]
    assert scheduler.list_jobs()[0]["pending"] is False
