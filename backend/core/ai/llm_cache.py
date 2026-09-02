"""应用层 AI 结果缓存：结构化阶段 / 识图命名 / 生图，降低重复 API 消耗。

设计：
- SQLite KV（{data_dir}/ai/cache/llm_cache.sqlite3），线程安全，路径惰性解析
  （跟随 backend.paths.config_path，测试可 monkeypatch 隔离）。
- 键 = sha256(规范化 JSON)：purpose / model / base_url / temperature / schema /
  messages / extra。多模态消息中的 data:image URL 取 sha256 摘要参与哈希，
  避免键体积膨胀且保证同一图片稳定命中。
- TTL 由 NEXUZ_AI_LLM_CACHE_TTL_HOURS 控制（默认 14 天），过期视为未命中，
  写入时顺带清理过期行。
- 开关：AiConfig.llm_cache_enabled（env NEXUZ_AI_LLM_CACHE 可覆盖）。

注意：只缓存"成功且可复现"的结果；失败重试路径不落缓存。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Sequence

_CACHE_VERSION = 1
_DEFAULT_TTL_H = 24 * 14
_MAX_VALUE_BYTES = 32 * 1024 * 1024  # 单条上限（生图 PNG 一般 < 10MB）

_db_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None


def _ttl_seconds() -> float:
    raw = os.environ.get("NEXUZ_AI_LLM_CACHE_TTL_HOURS", "")
    try:
        hours = float(raw) if raw.strip() else float(_DEFAULT_TTL_H)
    except (TypeError, ValueError):
        hours = float(_DEFAULT_TTL_H)
    return max(0.0, hours) * 3600.0


def _cache_dir(*, create: bool = True) -> Path:
    from backend.paths import ai_dir

    root = ai_dir(create=create) / "cache"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _db_path() -> Path:
    return _cache_dir() / "llm_cache.sqlite3"


def _get_conn() -> sqlite3.Connection:
    global _conn, _conn_path
    path = str(_db_path())
    with _db_lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            " key TEXT PRIMARY KEY,"
            " value BLOB NOT NULL,"
            " kind TEXT NOT NULL DEFAULT 'json',"
            " created_at REAL NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kv_created ON kv (created_at)"
        )
        # 命中率指标（进程间持久化；key ∈ hit/miss/miss_expired/miss_corrupt）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            " key TEXT PRIMARY KEY,"
            " value INTEGER NOT NULL"
            ")"
        )
        conn.commit()
        _conn = conn
        _conn_path = path
        return conn


def close_cache() -> None:
    """关闭缓存连接（数据目录迁移/测试隔离时调用）。"""
    global _conn, _conn_path
    with _db_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _conn_path = None


def enabled(cfg: Any = None) -> bool:
    """缓存总开关（AiConfig.llm_cache_enabled，env 已在 config 层合并）。"""
    if cfg is None:
        try:
            from backend.core.ai.config import get_ai_config

            cfg = get_ai_config()
        except Exception:
            return False
    return bool(getattr(cfg, "llm_cache_enabled", True))


# ---------------------------------------------------------------------------
# 键构造
# ---------------------------------------------------------------------------


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _message_part(part: Any) -> Any:
    if isinstance(part, dict):
        url_obj = part.get("image_url")
        url = url_obj.get("url") if isinstance(url_obj, dict) else None
        if isinstance(url, str) and url.startswith("data:"):
            # 大体积内联图片只参与哈希，不进键原文
            return {
                "type": "image_url",
                "sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            }
        return part
    return str(part)


def message_to_dict(message: Any) -> dict[str, Any]:
    """LangChain Message / (role, content) tuple / dict → 规范化字典。"""
    if isinstance(message, tuple):
        role = str(message[0]) if len(message) > 0 else ""
        content = message[1] if len(message) > 1 else ""
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
    if isinstance(content, list):
        content = [_message_part(p) for p in content]
    return {"role": str(role or ""), "content": content}


def make_key(
    *,
    purpose: str,
    model: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    schema_name: str = "",
    messages: Sequence[Any] = (),
    extra: dict[str, Any] | None = None,
) -> str:
    payload = {
        "v": _CACHE_VERSION,
        "purpose": str(purpose or ""),
        "model": str(model or ""),
        "base_url": str(base_url or ""),
        "temperature": float(temperature),
        "schema": str(schema_name or ""),
        "messages": [message_to_dict(m) for m in messages or []],
        "extra": extra or {},
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# KV 存取
# ---------------------------------------------------------------------------


def _bump_metric(conn: sqlite3.Connection, name: str, delta: int = 1) -> None:
    try:
        with _db_lock:
            conn.execute(
                "INSERT INTO metrics (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
                (name, delta),
            )
            conn.commit()
    except Exception:
        pass  # 指标失败不影响主流程


def get_json(key: str) -> Any | None:
    ttl = _ttl_seconds()
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT value, created_at FROM kv WHERE key = ?", (key,)
        ).fetchone()
    except Exception:
        return None
    if not row:
        _bump_metric(conn, "miss")
        return None
    if (time.time() - float(row[1])) > ttl:
        _bump_metric(conn, "miss_expired")
        return None
    try:
        value = json.loads(bytes(row[0]).decode("utf-8"))
    except Exception:
        _bump_metric(conn, "miss_corrupt")
        return None
    _bump_metric(conn, "hit")
    return value


def put_json(key: str, value: Any) -> None:
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        if len(blob) > _MAX_VALUE_BYTES:
            return
        conn = _get_conn()
        with _db_lock:
            conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, kind, created_at) "
                "VALUES (?, ?, 'json', ?)",
                (key, blob, time.time()),
            )
            conn.commit()
            _sweep_expired(conn)
    except Exception:
        pass  # 缓存失败不影响主流程


def _sweep_expired(conn: sqlite3.Connection) -> None:
    ttl = _ttl_seconds()
    if ttl <= 0:
        return
    cutoff = time.time() - ttl
    # 顺带清理时低频触发：仅当过期行足够多才 DELETE（避免每次写都全表扫）
    try:
        conn.execute(
            "DELETE FROM kv WHERE created_at < ? AND key IN "
            "(SELECT key FROM kv WHERE created_at < ? LIMIT 64)",
            (cutoff, cutoff),
        )
        conn.commit()
    except Exception:
        pass


def get_blob(key: str) -> bytes | None:
    ttl = _ttl_seconds()
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT value, created_at FROM kv WHERE key = ?", (key,)
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    if (time.time() - float(row[1])) > ttl:
        return None
    try:
        return bytes(row[0])
    except Exception:
        return None


def put_blob(key: str, data: bytes) -> None:
    try:
        data = bytes(data)
        if not data or len(data) > _MAX_VALUE_BYTES:
            return
        conn = _get_conn()
        with _db_lock:
            conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, kind, created_at) "
                "VALUES (?, ?, 'blob', ?)",
                (key, data, time.time()),
            )
            conn.commit()
            _sweep_expired(conn)
    except Exception:
        pass


def clear() -> int:
    """手动清空缓存，返回清除条数（命中率指标一并归零）。"""
    try:
        conn = _get_conn()
        with _db_lock:
            n = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
            conn.execute("DELETE FROM kv")
            conn.execute("DELETE FROM metrics")
            conn.commit()
        return int(n)
    except Exception:
        return 0


def stats() -> dict[str, Any]:
    """缓存概况（设置页展示/诊断用），含累计命中率。"""
    try:
        conn = _get_conn()
        count, size = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(value)), 0) FROM kv"
        ).fetchone()
        metrics = {
            str(k): int(v)
            for k, v in conn.execute("SELECT key, value FROM metrics").fetchall()
        }
        hits = metrics.get("hit", 0)
        misses = (
            metrics.get("miss", 0)
            + metrics.get("miss_expired", 0)
            + metrics.get("miss_corrupt", 0)
        )
        total = hits + misses
        return {
            "count": int(count),
            "bytes": int(size),
            "path": str(_db_path()),
            "hits": hits,
            "misses": misses,
            "miss_expired": metrics.get("miss_expired", 0),
            "hit_rate": round(hits / total, 4) if total else None,
        }
    except Exception as exc:
        return {
            "count": 0,
            "bytes": 0,
            "hits": 0,
            "misses": 0,
            "miss_expired": 0,
            "hit_rate": None,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# 结构化结果（pydantic / dict）
# ---------------------------------------------------------------------------


def store_structured(key: str, result: Any) -> None:
    if hasattr(result, "model_dump"):
        try:
            data = result.model_dump()
        except Exception:
            return
    else:
        data = result
    put_json(key, {"kind": "structured", "name": type(result).__name__, "data": data})


def load_structured(key: str, schema: type) -> Any | None:
    """命中返回 schema 实例（或 dict）；schema 漂移 / 未命中返回 None。"""
    rec = get_json(key)
    if not isinstance(rec, dict) or rec.get("kind") != "structured":
        return None
    data = rec.get("data")
    try:
        if hasattr(schema, "model_validate"):
            return schema.model_validate(data)
        return schema(**data)
    except Exception:
        return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
