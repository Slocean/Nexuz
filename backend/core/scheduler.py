"""APScheduler-backed flow triggers with disk persistence."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_scheduler = None
_lock = threading.Lock()


def get_scheduler():
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = FlowScheduler()
        return _scheduler


def _jobs_file() -> Path:
    from backend.paths import get_data_dir

    folder = get_data_dir(create=True) / "schedules"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "jobs.json"


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
                    "interval_seconds": meta.get("interval_seconds"),
                    "run_at": meta.get("run_at"),
                    "cron_expression": meta.get("cron_expression"),
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
        self._persist()

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
        persist: bool = True,
    ) -> None:
        if not self._aps:
            raise RuntimeError("未安装 APScheduler，请执行: pip install APScheduler")

        # Remove without persist — we'll persist once at the end
        self._jobs.pop(job_id, None)
        if self._aps:
            try:
                self._aps.remove_job(job_id)
            except Exception:
                pass

        snapshot = json.loads(json.dumps(flow))  # deep copy via json
        meta = {
            "trigger_type": trigger_type,
            "file_path": file_path,
            "flow": snapshot if not file_path else None,
            "interval_seconds": float(interval_seconds or 60),
            "run_at": str(run_at or ""),
            "cron_expression": str(cron_expression or ""),
        }

        def _run():
            try:
                from backend.core.interpreter import get_interpreter
                from backend.core.runtime_log import get_runtime_log_manager

                payload = snapshot
                fp = meta.get("file_path") or file_path
                if fp and Path(fp).is_file():
                    payload = json.loads(Path(fp).read_text(encoding="utf-8"))
                elif meta.get("flow"):
                    payload = meta["flow"]
                payload = dict(payload)
                if fp:
                    payload["__file_path__"] = fp
                interp = get_interpreter()
                if interp.running:
                    raise RuntimeError("已有流程正在执行，跳过本次定时任务")
                get_runtime_log_manager().start(payload)
                interp.run_flow(payload, step_mode=False)
                if self._emit:
                    self._emit("schedule_fired", {"job_id": job_id})
            except Exception as exc:
                try:
                    get_runtime_log_manager().finish({"ok": False, "error": str(exc)})
                except Exception:
                    pass
                if self._emit:
                    self._emit("schedule_error", {"job_id": job_id, "error": str(exc)})

        if trigger_type == "once":
            if not str(run_at).strip():
                raise ValueError("once 触发需要 run_at")
            run_date = datetime.strptime(str(run_at).strip(), "%Y-%m-%d %H:%M:%S")
            if run_date <= datetime.now():
                raise ValueError("单次触发时间已过期，请重新设置")
            self._aps.add_job(_run, "date", run_date=run_date, id=job_id, replace_existing=True)
            meta["next_run"] = str(run_at).strip()
        elif trigger_type == "cron":
            parts = str(cron_expression).split()
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
            meta["next_run"] = str(cron_expression)
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
            meta["interval_seconds"] = secs

        self._jobs[job_id] = meta
        if persist:
            self._persist()

    def _persist(self) -> None:
        rows = []
        for jid, meta in self._jobs.items():
            row = {
                "job_id": jid,
                "trigger_type": meta.get("trigger_type"),
                "interval_seconds": meta.get("interval_seconds", 60),
                "run_at": meta.get("run_at") or "",
                "cron_expression": meta.get("cron_expression") or "",
                "file_path": meta.get("file_path") or "",
            }
            # Only embed flow when no file on disk (unsaved flow snapshot)
            fp = row["file_path"]
            if not fp or not Path(fp).is_file():
                if meta.get("flow"):
                    row["flow"] = meta["flow"]
            rows.append(row)
        path = _jobs_file()
        try:
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("无法写入定时任务: %s", exc)

    def restore_from_disk(self) -> int:
        """Re-register jobs from schedules/jobs.json. Returns restored count."""
        if not self._aps:
            return 0
        path = _jobs_file()
        if not path.is_file():
            return 0
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("无法读取定时任务: %s", exc)
            return 0
        if not isinstance(rows, list):
            return 0
        restored = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                continue
            file_path = str(row.get("file_path") or "").strip() or None
            flow = row.get("flow") if isinstance(row.get("flow"), dict) else None
            if file_path and Path(file_path).is_file():
                try:
                    flow = json.loads(Path(file_path).read_text(encoding="utf-8"))
                except Exception:
                    flow = flow
            if not isinstance(flow, dict):
                logger.warning("跳过定时任务（无流程）: %s", job_id)
                continue
            trigger_type = str(row.get("trigger_type") or "interval")
            try:
                self.register_flow_job(
                    job_id=job_id,
                    flow=flow,
                    file_path=file_path,
                    trigger_type=trigger_type,
                    interval_seconds=float(row.get("interval_seconds") or 60),
                    run_at=str(row.get("run_at") or ""),
                    cron_expression=str(row.get("cron_expression") or ""),
                    persist=False,
                )
                restored += 1
            except Exception as exc:
                logger.warning("恢复定时任务失败 %s: %s", job_id, exc)
        if restored:
            self._persist()
        return restored
