"""Append-only AI orchestration audit log under data_dir/ai/audit/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.paths import ai_dir


def _audit_dir(*, create: bool = True) -> Path:
    root = ai_dir(create=create) / "audit"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def write_audit_event(event: dict[str, Any]) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _audit_dir(create=True) / f"{day}.jsonl"
    row = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def list_recent_audit(*, limit: int = 50) -> list[dict[str, Any]]:
    root = _audit_dir(create=True)
    files = sorted(root.glob("*.jsonl"), reverse=True)
    rows: list[dict[str, Any]] = []
    for fp in files:
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
            if len(rows) >= limit:
                return rows
    return rows
