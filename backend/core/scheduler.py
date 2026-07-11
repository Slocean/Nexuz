"""APScheduler-backed flow triggers."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_scheduler = None
_lock = threading.Lock()


def get_scheduler():
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = FlowScheduler()
        return _scheduler


class FlowScheduler:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._aps = None
        self._emit = None
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._aps = BackgroundScheduler()
            self._aps.start()
        except ImportError:
            self._aps = None

    def set_emit(self, emit) -> None:
        self._emit = emit

    @property
    def available(self) -> bool:
        return self._aps is not None

    def list_jobs(self) -> list[dict]:
        out = []
        for jid, meta in self._jobs.items():
            out.append(
                {
                    "job_id": jid,
                    "trigger_type": meta.get("trigger_type"),
                    "next_run": meta.get("next_run"),
                    "file_path": meta.get("file_path"),
                }
            )
        return out

    def remove_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        if self._aps:
            try:
                self._aps.remove_job(job_id)
            except Exception:
                pass

    def register_flow_job(
        self,
        *,
        job_id: str,
        flow: dict,
        file_path: str | None,
        trigger_type: str,
        interval_seconds: float,
        run_at: str,
        cron_expression: str,
    ) -> None:
        if not self._aps:
            raise RuntimeError("未安装 APScheduler，请执行: pip install APScheduler")

        self.remove_job(job_id)
        snapshot = json.loads(json.dumps(flow))  # deep copy via json
        meta = {
            "trigger_type": trigger_type,
            "file_path": file_path,
            "flow": snapshot,
        }

        def _run():
            try:
                from backend.core.interpreter import get_interpreter

                # Prefer file on disk if present (fresh)
                payload = snapshot
                if file_path and Path(file_path).is_file():
                    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
                get_interpreter().run_flow(payload, step_mode=False)
                if self._emit:
                    self._emit("schedule_fired", {"job_id": job_id})
            except Exception as exc:
                if self._emit:
                    self._emit("schedule_error", {"job_id": job_id, "error": str(exc)})

        if trigger_type == "once":
            if not run_at.strip():
                raise ValueError("once 触发需要 run_at")
            run_date = datetime.strptime(run_at.strip(), "%Y-%m-%d %H:%M:%S")
            self._aps.add_job(_run, "date", run_date=run_date, id=job_id, replace_existing=True)
            meta["next_run"] = run_at
        elif trigger_type == "cron":
            parts = cron_expression.split()
            if len(parts) != 5:
                raise ValueError("cron 需 5 段: 分 时 日 月 周")
            minute, hour, day, month, day_of_week = parts
            self._aps.add_job(
                _run,
                "cron",
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                id=job_id,
                replace_existing=True,
            )
            meta["next_run"] = cron_expression
        else:
            secs = max(1.0, float(interval_seconds or 60))
            self._aps.add_job(
                _run,
                "interval",
                seconds=secs,
                id=job_id,
                replace_existing=True,
            )
            meta["next_run"] = f"every {secs}s"

        self._jobs[job_id] = meta
