"""Unified log categories, app-level JSONL sinks, and event classification."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.paths import get_data_dir

CATEGORIES = ("system", "runtime", "audit", "diag")
LEVELS = ("debug", "info", "warn", "error", "ok")
SCOPES = ("app", "flow", "run", "node")

_MAX_APP_PART_BYTES = 5 * 1024 * 1024
_MAX_APP_PARTS = 3

# event name → default category (override via payload.category)
_EVENT_CATEGORY: dict[str, str] = {
    "node_start": "runtime",
    "node_end": "runtime",
    "flow_finished": "runtime",
    "flow_stopping": "runtime",
    "flow_stopped": "runtime",
    "flow_paused": "runtime",
    "flow_resumed": "runtime",
    "flow_breakpoint": "runtime",
    "flow_stepping": "runtime",
    "flow_debug": "runtime",
    "schedule_fired": "runtime",
    "schedule_error": "runtime",
    "recording_stopped": "audit",
    "force_reset": "system",
    "plugin_mode_changed": "system",
    "update_download_progress": "system",
    "hotkey_run": "system",
    "memory_sample": "diag",
    "run_started": "runtime",
    "run_log_closed": "runtime",
}


def normalize_category(raw: Any, *, default: str = "runtime") -> str:
    s = str(raw or "").strip().lower()
    return s if s in CATEGORIES else default


def normalize_level(raw: Any, *, default: str = "info") -> str:
    s = str(raw or "").strip().lower()
    if s in ("warning",):
        return "warn"
    if s in ("success", "ok"):
        return "ok"
    return s if s in LEVELS else default


def normalize_scope(raw: Any, *, default: str = "app") -> str:
    s = str(raw or "").strip().lower()
    return s if s in SCOPES else default


def classify_event(event: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("category"):
        return normalize_category(payload.get("category"))
    ev = str(event or "")
    if ev == "log":
        return normalize_category(payload.get("category"), default="runtime")
    return _EVENT_CATEGORY.get(ev, "system" if ev.startswith("sys_") else "runtime")


def infer_scope(event: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("scope"):
        return normalize_scope(payload.get("scope"))
    if payload.get("node_id") or payload.get("nodeId"):
        return "node"
    ev = str(event or "")
    if ev.startswith("node_") or ev.startswith("flow_") or ev in (
        "schedule_fired",
        "schedule_error",
        "run_started",
        "run_log_closed",
    ):
        return "run"
    return "app"


def enrich_payload(
    event: str,
    payload: dict[str, Any] | None,
    *,
    category: str | None = None,
    level: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    out = dict(payload or {})
    out["category"] = normalize_category(
        category or out.get("category") or classify_event(event, out)
    )
    if level is not None or out.get("level"):
        out["level"] = normalize_level(level if level is not None else out.get("level"))
    elif event == "node_end":
        if out.get("stopped"):
            out["level"] = "warn"
        elif out.get("ok") is False:
            out["level"] = "error"
        else:
            out["level"] = "ok"
    elif event in ("flow_paused", "flow_stopping", "flow_breakpoint", "schedule_error"):
        out["level"] = "warn"
    elif event in ("flow_finished",) and not out.get("ok", True):
        out["level"] = "error"
    else:
        out.setdefault("level", "info")
    out["scope"] = normalize_scope(scope or out.get("scope") or infer_scope(event, out))
    return out


class _AppCategorySink:
    """Rolling JSONL under data/logs/app/{category}.jsonl (+ .1 .2 rotations)."""

    def __init__(self, category: str) -> None:
        self.category = category
        self._lock = threading.RLock()
        base = get_data_dir(create=True) / "logs" / "app"
        base.mkdir(parents=True, exist_ok=True)
        self._path = base / f"{category}.jsonl"

    def write(self, row: dict[str, Any]) -> None:
        with self._lock:
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)
            encoded = line.encode("utf-8") + b"\n"
            try:
                if self._path.exists() and self._path.stat().st_size + len(encoded) > _MAX_APP_PART_BYTES:
                    self._rotate()
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def _rotate(self) -> None:
        # category.jsonl -> category.1.jsonl -> ... drop oldest
        for i in range(_MAX_APP_PARTS - 1, 0, -1):
            src = self._path.with_name(f"{self.category}.{i}.jsonl")
            dst = self._path.with_name(f"{self.category}.{i + 1}.jsonl")
            if i + 1 >= _MAX_APP_PARTS:
                try:
                    src.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if src.exists():
                try:
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
                except OSError:
                    pass
        try:
            if self._path.exists():
                rotated = self._path.with_name(f"{self.category}.1.jsonl")
                if rotated.exists():
                    rotated.unlink()
                self._path.rename(rotated)
        except OSError:
            pass

    def as_text(self, *, limit_lines: int = 5000) -> str:
        paths: list[Path] = []
        for i in range(_MAX_APP_PARTS - 1, 0, -1):
            p = self._path.with_name(f"{self.category}.{i}.jsonl")
            if p.is_file():
                paths.append(p)
        if self._path.is_file():
            paths.append(self._path)
        lines_out: list[str] = [f"应用日志 · {self.category}", ""]
        buf: list[str] = []
        for path in paths:
            try:
                buf.extend(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                continue
        for line in buf[-limit_lines:]:
            try:
                row = json.loads(line)
                stamp = datetime.fromtimestamp(float(row.get("ts") or 0)).isoformat(
                    sep=" ", timespec="milliseconds"
                )
                msg = row.get("message") or row.get("event") or ""
                detail = row.get("detail")
                extra = ""
                if detail is not None:
                    extra = " " + json.dumps(detail, ensure_ascii=False, separators=(",", ":"), default=str)
                lines_out.append(
                    f"{stamp} [{row.get('level') or 'info'}] [{row.get('category') or self.category}] {msg}{extra}"
                )
            except Exception:
                lines_out.append(line)
        return "\n".join(lines_out)


class AppLogManager:
    def __init__(self) -> None:
        self._sinks = {
            "system": _AppCategorySink("system"),
            "audit": _AppCategorySink("audit"),
            "diag": _AppCategorySink("diag"),
        }
        self._diag_enabled = False
        self._lock = threading.RLock()

    def set_diag_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._diag_enabled = bool(enabled)

    def diag_enabled(self) -> bool:
        with self._lock:
            return self._diag_enabled

    def write_row(self, row: dict[str, Any]) -> None:
        cat = normalize_category(row.get("category"), default="system")
        if cat == "runtime":
            return  # runtime uses flow-scoped session
        if cat == "diag" and not self.diag_enabled():
            return
        sink = self._sinks.get(cat) or self._sinks["system"]
        sink.write(row)

    def export_text(self, categories: list[str] | None = None) -> str:
        cats = categories or ["system", "audit"]
        parts: list[str] = []
        for c in cats:
            c = normalize_category(c, default="")
            if c in self._sinks:
                parts.append(self._sinks[c].as_text())
                parts.append("")
        return "\n".join(parts).rstrip() + "\n"


_app_logs = AppLogManager()


def get_app_log_manager() -> AppLogManager:
    return _app_logs


def build_log_row(
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    category: str | None = None,
    level: str | None = None,
    scope: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    enriched = enrich_payload(event, payload, category=category, level=level, scope=scope)
    msg = message if message is not None else enriched.get("message")
    if msg is None:
        msg = str(event)
    row = {
        "ts": time.time(),
        "event": str(event),
        "category": enriched["category"],
        "level": enriched["level"],
        "scope": enriched["scope"],
        "message": str(msg),
        "payload": enriched,
    }
    if enriched.get("node_id") or enriched.get("nodeId"):
        row["node_id"] = enriched.get("node_id") or enriched.get("nodeId")
    if enriched.get("detail") is not None:
        row["detail"] = enriched.get("detail")
    return row
