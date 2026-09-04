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


def test_mcp_origin_job_reapplies_floor_at_fire(tmp_path, monkeypatch):
    """MCP 注册的定时任务：注册后流程文件被改写为危险命令，触发时仍被拦截。"""
    from backend.core.registry import BLOCK_REGISTRY, register_block

    monkeypatch.setattr(
        "backend.core.scheduler._failures_file", lambda: tmp_path / "failures.jsonl"
    )
    # 注册 stub 以通过参数校验（真实 python_script 可能未加载）
    previous = BLOCK_REGISTRY.get("python_script")
    register_block({"type": "python_script", "inputs": [], "outputs": []}, lambda *a, **k: {})
    try:
        flow_file = tmp_path / "flow.flow.json"
        flow_file.write_text(
            json.dumps(
                {
                    "name": "self_sched",
                    "entry": "n1",
                    "nodes": {"n1": {"type": "python_script", "params": {}}},
                }
            ),
            encoding="utf-8",
        )
        interp = _FakeInterpreter(running=False)
        monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
        monkeypatch.setattr(
            "backend.core.runtime_log.get_runtime_log_manager",
            lambda: _FakeRuntimeLogs(),
        )
        scheduler = FlowScheduler()
        scheduler._aps = None
        scheduler.set_emit(lambda event, payload: None)
        meta = {
            "trigger_type": "interval",
            "file_path": str(flow_file),
            "flow": None,
            "origin": "mcp",
        }
        scheduler._run_job("job-1", snapshot={}, meta=meta, file_path=str(flow_file))

        assert interp.started == []
        row = json.loads(
            (tmp_path / "failures.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert row["reason"] == "policy_blocked"
    finally:
        if previous is None:
            BLOCK_REGISTRY.pop("python_script", None)
        else:
            BLOCK_REGISTRY["python_script"] = previous


def test_local_origin_job_keeps_legacy_behavior(tmp_path, monkeypatch):
    """用户自己注册的定时任务（非 MCP 来源）：legacy 流程保持既有行为。"""
    from backend.core.registry import BLOCK_REGISTRY, register_block

    monkeypatch.setattr(
        "backend.core.scheduler._failures_file", lambda: tmp_path / "failures.jsonl"
    )
    previous = BLOCK_REGISTRY.get("python_script")
    register_block({"type": "python_script", "inputs": [], "outputs": []}, lambda *a, **k: {})
    try:
        flow_file = tmp_path / "flow.flow.json"
        flow_file.write_text(
            json.dumps(
                {
                    "name": "local",
                    "entry": "n1",
                    "nodes": {"n1": {"type": "python_script", "params": {}}},
                }
            ),
            encoding="utf-8",
        )
        interp = _FakeInterpreter(running=False)
        monkeypatch.setattr("backend.core.interpreter.get_interpreter", lambda: interp)
        monkeypatch.setattr(
            "backend.core.runtime_log.get_runtime_log_manager",
            lambda: _FakeRuntimeLogs(),
        )
        scheduler = FlowScheduler()
        scheduler._aps = None
        scheduler.set_emit(lambda event, payload: None)
        meta = {
            "trigger_type": "interval",
            "file_path": str(flow_file),
            "flow": None,
            "origin": "",
        }
        scheduler._run_job("job-2", snapshot={}, meta=meta, file_path=str(flow_file))

        # 无下限标记 → legacy 放行 → 解释器收到 payload
        assert len(interp.started) == 1
        assert "__policy_floor__" not in interp.started[0]
    finally:
        if previous is None:
            BLOCK_REGISTRY.pop("python_script", None)
        else:
            BLOCK_REGISTRY["python_script"] = previous
