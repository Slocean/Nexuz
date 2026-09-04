"""APScheduler-backed flow triggers with disk persistence."""

from __future__ import annotations

import json
import logging
import threading
import time
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


def _failures_file() -> Path:
    return _jobs_file().with_name("failures.jsonl")


class FlowScheduler:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._last_failure: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.RLock()
        self._drain_scheduled = False
        self._aps = None
        self._emit = None
        self._load_last_failures()
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
        with self._state_lock:
            for jid, meta in self._jobs.items():
                pending = self._pending.get(jid)
                out.append(
                    {
                        "job_id": jid,
                        "trigger_type": meta.get("trigger_type"),
                        "next_run": meta.get("next_run"),
                        "file_path": meta.get("file_path"),
                        "interval_seconds": meta.get("interval_seconds"),
                        "run_at": meta.get("run_at"),
                        "cron_expression": meta.get("cron_expression"),
                        "pending": bool(pending),
                        "pending_since": pending.get("queued_at") if pending else None,
                        "last_failure": self._last_failure.get(jid),
                    }
                )
        return out

    def remove_job(self, job_id: str) -> None:
        with self._state_lock:
            self._jobs.pop(job_id, None)
            self._pending.pop(job_id, None)
        if self._aps:
            try:
                self._aps.remove_job(job_id)
            except Exception:
                pass
        self._persist()

    def _load_last_failures(self) -> None:
        path = _failures_file()
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-1000:]
            for line in lines:
                row = json.loads(line)
                if isinstance(row, dict) and row.get("job_id"):
                    self._last_failure[str(row["job_id"])] = row
        except Exception as exc:
            logger.warning("无法读取定时任务失败记录: %s", exc)

    def _record_failure(
        self,
        job_id: str,
        *,
        reason: str,
        error: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        info = meta or self._jobs.get(job_id) or {}
        row = {
            "ts": time.time(),
            "job_id": job_id,
            "reason": reason,
            "error": str(error),
            "trigger_type": info.get("trigger_type"),
            "file_path": info.get("file_path"),
        }
        with self._state_lock:
            self._last_failure[job_id] = row
            try:
                path = _failures_file()
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning("无法写入定时任务失败记录: %s", exc)
        return row

    def _queue_pending(
        self,
        job_id: str,
        payload: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        queued_at = time.time()
        with self._state_lock:
            if job_id in self._pending:
                error = "该定时任务已有一次待补跑，本次触发已丢弃"
                self._record_failure(
                    job_id,
                    reason="pending_full",
                    error=error,
                    meta=meta,
                )
                if self._emit:
                    self._emit(
                        "schedule_error",
                        {"job_id": job_id, "reason": "pending_full", "error": error},
                    )
                return
            self._pending[job_id] = {
                "payload": payload,
                "meta": dict(meta),
                "queued_at": queued_at,
            }
        if self._emit:
            self._emit("schedule_pending", {"job_id": job_id, "queued_at": queued_at})

    def _start_or_queue(
        self,
        job_id: str,
        payload: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        from backend.core.block_params_validate import validate_flow_params
        from backend.core.execution_policy import resolve_execution_policy, scan_flow_violations
        from backend.core.interpreter import get_interpreter
        from backend.core.runtime_log import get_runtime_log_manager

        issues = validate_flow_params(payload)
        errors = [issue for issue in issues if issue.get("level") == "error"]
        if errors:
            message = f"流程参数校验未通过：{errors[0].get('message')}"
            self._record_failure(
                job_id,
                reason="validation_error",
                error=message,
                meta=meta,
            )
            if self._emit:
                self._emit(
                    "schedule_error",
                    {
                        "job_id": job_id,
                        "reason": "validation_error",
                        "error": message,
                    },
                )
            return
        # 与 api.run_flow 同一道预扫描：高危积木在启动前整体拒绝，
        # 而不是只依赖运行时逐节点检查兜底。
        # 外部 AI（MCP）注册的任务每次触发都重新套用下限——流程文件可能
        # 在注册后被改写（TOCTOU），不能只靠注册时的内容。
        from backend.core.execution_policy import apply_policy_floor

        execution_policy = apply_policy_floor(
            resolve_execution_policy(payload), payload.get("__policy_floor__")
        )
        violations = scan_flow_violations(payload, execution_policy)
        if violations:
            labels = "、".join(
                f"{item['block_type']}（{item['node_id']}）" for item in violations[:5]
            )
            message = f"流程含未授权的高危积木：{labels}"
            self._record_failure(job_id, reason="policy_blocked", error=message, meta=meta)
            if self._emit:
                self._emit(
                    "schedule_error",
                    {"job_id": job_id, "reason": "policy_blocked", "error": message},
                )
            return
        interp = get_interpreter()
        if interp.running:
            self._queue_pending(job_id, payload, meta)
            return
        try:
            get_runtime_log_manager().start(payload)
            interp.run_flow(payload, step_mode=False)
            if self._emit:
                self._emit("schedule_fired", {"job_id": job_id})
        except Exception as exc:
            if interp.running:
                self._queue_pending(job_id, payload, meta)
                return
            try:
                get_runtime_log_manager().finish({"ok": False, "error": str(exc)})
            except Exception:
                pass
            self._record_failure(
                job_id,
                reason="execution_error",
                error=str(exc),
                meta=meta,
            )
            if self._emit:
                self._emit(
                    "schedule_error",
                    {"job_id": job_id, "reason": "execution_error", "error": str(exc)},
                )

    def _run_job(
        self,
        job_id: str,
        snapshot: dict[str, Any],
        meta: dict[str, Any],
        file_path: str | None,
    ) -> None:
        try:
            payload = snapshot
            fp = meta.get("file_path") or file_path
            if fp and Path(fp).is_file():
                payload = json.loads(Path(fp).read_text(encoding="utf-8"))
            elif meta.get("flow"):
                payload = meta["flow"]
            payload = dict(payload)
            if fp:
                payload["__file_path__"] = fp
            # 外部 AI 注册的任务：磁盘上的流程文件可能已被改写，触发时按
            # origin 重新注入下限，保证危险命令类在每次触发都被拒绝。
            if str(meta.get("origin") or "") == "mcp":
                from backend.core.execution_policy import mcp_policy_floor

                payload["__policy_floor__"] = mcp_policy_floor()
            self._start_or_queue(job_id, payload, meta)
        except Exception as exc:
            self._record_failure(
                job_id,
                reason="execution_error",
                error=str(exc),
                meta=meta,
            )
            if self._emit:
                self._emit(
                    "schedule_error",
                    {"job_id": job_id, "reason": "execution_error", "error": str(exc)},
                )

    def on_flow_finished(self) -> None:
        with self._state_lock:
            if not self._pending or self._drain_scheduled:
                return
            self._drain_scheduled = True
        timer = threading.Timer(0.15, self._drain_pending_once)
        timer.daemon = True
        timer.start()

    def _drain_pending_once(self) -> None:
        from backend.core.interpreter import get_interpreter

        with self._state_lock:
            self._drain_scheduled = False
        if get_interpreter().running:
            self.on_flow_finished()
            return
        with self._state_lock:
            if not self._pending:
                return
            job_id, pending = min(
                self._pending.items(),
                key=lambda item: float(item[1].get("queued_at") or 0),
            )
            self._pending.pop(job_id, None)
        self._start_or_queue(job_id, pending["payload"], pending["meta"])

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
        origin: str | None = None,
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
            "origin": str(origin or ""),
        }

        def _run():
            self._run_job(job_id, snapshot, meta, file_path)

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
                "origin": meta.get("origin") or "",
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
                    origin=str(row.get("origin") or "") or None,
                )
                restored += 1
            except Exception as exc:
                logger.warning("恢复定时任务失败 %s: %s", job_id, exc)
        if restored:
            self._persist()
        return restored

    def reload_from_disk(self) -> int:
        """Replace in-memory jobs with the definitions currently on disk."""
        with self._state_lock:
            job_ids = list(self._jobs)
            self._jobs.clear()
            self._pending.clear()
        if self._aps:
            for job_id in job_ids:
                try:
                    self._aps.remove_job(job_id)
                except Exception:
                    pass
        return self.restore_from_disk()
