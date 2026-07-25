"""LangGraph SqliteSaver under {data_dir}/ai/checkpoints.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from backend.paths import ai_dir

_saver: SqliteSaver | None = None
_conn: sqlite3.Connection | None = None


def checkpoint_db_path(*, create: bool = True) -> Path:
    root = ai_dir(create=create)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root / "checkpoints.db"


def get_checkpointer(*, path: Path | None = None) -> SqliteSaver:
    """Process-wide SqliteSaver (sync). Safe for desktop single-process app."""
    global _saver, _conn
    if _saver is not None and path is None:
        return _saver
    db = path or checkpoint_db_path(create=True)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    saver = SqliteSaver(conn)
    if path is None:
        _conn = conn
        _saver = saver
    return saver


def reset_checkpointer_for_tests() -> None:
    global _saver, _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _saver = None
    _conn = None


def thread_config(conversation_id: str, **extra: Any) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(conversation_id), **extra}}
