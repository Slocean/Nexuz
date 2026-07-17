"""Bounded, flow-scoped runtime event logs.

Each run writes to its own directory/file series so logs from different flows
can never be mixed.  Only the newest parts of a run are retained to keep disk
usage bounded during unattended automation.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.paths import get_data_dir

_MAX_PART_BYTES = 10 * 1024 * 1024
_MAX_PARTS = 3


def _safe_name(value: Any, fallback: str, limit: int = 48) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._")
    return (text or fallback)[:limit]


def _flow_identity(flow: dict[str, Any]) -> tuple[str, str, str]:
    name = str(flow.get("name") or "未命名流程").strip() or "未命名流程"
    file_path = str(flow.get("__file_path__") or "").strip()
    flow_id = str(flow.get("flow_id") or "").strip()
    if not flow_id:
        source = str(Path(file_path).resolve()) if file_path else name
        flow_id = "legacy-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return flow_id, name, file_path


class RuntimeLogSession:
    def __init__(self, flow: dict[str, Any]) -> None:
        flow_id, flow_name, file_path = _flow_identity(flow)
        self.run_id = uuid.uuid4().hex[:12]
        self.flow_id = flow_id
        self.flow_name = flow_name
        self.flow_file = file_path
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.record_count = 0
        self._lock = threading.RLock()
        self._file = None
        self._part_no = 0
        self._parts: list[Path] = []

        flow_dir = (
            get_data_dir(create=True)
            / "logs"
            / f"{_safe_name(flow_id, 'flow')}__{_safe_name(flow_name, 'unnamed')}"
        )
        flow_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self.started_at).strftime("%Y%m%d_%H%M%S")
        self._base = flow_dir / f"{stamp}__{_safe_name(flow_name, 'unnamed')}__{self.run_id}"
        self._open_next_part()
        self.write(
            "run_started",
            {
                "run_id": self.run_id,
                "flow_id": self.flow_id,
                "flow_name": self.flow_name,
                "flow_file": self.flow_file,
            },
        )

    def _open_next_part(self) -> None:
        if self._file is not None:
            self._file.close()
        self._part_no += 1
        path = Path(f"{self._base}.part{self._part_no:03d}.jsonl")
        self._file = path.open("w", encoding="utf-8", buffering=64 * 1024)
        self._parts.append(path)
        while len(self._parts) > _MAX_PARTS:
            old = self._parts.pop(0)
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

    def write(self, event: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._file is None:
                return
            row = {
                "ts": time.time(),
                "run_id": self.run_id,
                "flow_id": self.flow_id,
                "flow_name": self.flow_name,
                "event": str(event),
                "payload": payload if isinstance(payload, dict) else {},
            }
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)
            if self._file.tell() + len(line.encode("utf-8")) + 1 > _MAX_PART_BYTES:
                self._open_next_part()
            self._file.write(line + "\n")
            self.record_count += 1

    def close(self, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._file is None:
                return
            self.write("run_log_closed", result or {})
            self.ended_at = time.time()
            self._file.close()
            self._file = None

    def info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "flow_id": self.flow_id,
                "flow_name": self.flow_name,
                "flow_file": self.flow_file,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "record_count": self.record_count,
                "parts": [str(p) for p in self._parts if p.is_file()],
                "folder": str(self._base.parent),
            }

    def as_text(self) -> str:
        rows: list[str] = [
            f"流程：{self.flow_name}",
            f"流程 ID：{self.flow_id}",
            f"流程文件：{self.flow_file or '未保存'}",
            f"运行 ID：{self.run_id}",
            "",
        ]
        with self._lock:
            if self._file is not None:
                self._file.flush()
            parts = list(self._parts)
        for path in parts:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                    stamp = datetime.fromtimestamp(float(row.get("ts") or 0)).isoformat(
                        sep=" ", timespec="milliseconds"
                    )
                    event = str(row.get("event") or "")
                    payload = json.dumps(
                        row.get("payload") or {}, ensure_ascii=False, separators=(",", ":")
                    )
                    rows.append(f"{stamp} [{event}] {payload}")
                except Exception:
                    rows.append(line)
        return "\n".join(rows)


class RuntimeLogManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: RuntimeLogSession | None = None
        self._last: RuntimeLogSession | None = None

    def start(self, flow: dict[str, Any]) -> RuntimeLogSession:
        with self._lock:
            if self._active is not None:
                raise RuntimeError("已有流程日志会话正在记录")
            self._active = RuntimeLogSession(flow)
            return self._active

    def write(self, event: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            session = self._active
        if session is not None:
            session.write(event, payload)

    def finish(self, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            session = self._active
            self._active = None
            if session is None:
                return None
            session.close(result)
            self._last = session
            return session.info()

    def info(self) -> dict[str, Any] | None:
        with self._lock:
            session = self._active or self._last
        return session.info() if session else None

    def export_text(self) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            session = self._active or self._last
        if session is None:
            return None
        return session.as_text(), session.info()


_manager = RuntimeLogManager()


def get_runtime_log_manager() -> RuntimeLogManager:
    return _manager
