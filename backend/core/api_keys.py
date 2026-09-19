"""服务器端 API Key：分能力凭证（Web 界面生成，服务器形态独有）。

模型：
- 主密钥（master）：服务器启动 token（--token-file / NEXUZ_TOKEN env / 数据目录
  持久化），全权——含 API Key 管理本身；
- API Key：由主密钥在 Web 界面签发，**只存 sha256 哈希**（明文仅创建时展示一次），
  可勾选能力（scopes）与积木白名单（block_allowlist，空 = 不限）；
- 无 scope / 不认识的凭证 → 401；有凭证但越权 → 403。

能力（scopes）与接口的映射见 METHOD_SCOPES / TOOL_SCOPES；块级限制在
run_block / run_flow 的 dispatch 层强制（白名单非空时，流程内所有节点类型
必须 ⊆ 白名单，运行期经 __policy_floor__ deny 再拦一次）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

KEY_PREFIX = "nxz_"

# 能力清单（Web 界面勾选项）
SCOPES: dict[str, str] = {
    "catalog": "积木目录与 schema 查询",
    "run_block": "执行单积木（可另设积木白名单）",
    "run_flow": "运行流程与运行控制（启动/暂停/停止）",
    "flows": "流程库管理（查看/保存/删除）",
    "schedules": "定时任务管理（列表/删除）",
    "runs": "运行记录与日志读取",
}

# /api/<method> → 所需 scope；None = 任意已认证身份；不在表内 = 仅主密钥
METHOD_SCOPES: dict[str, str | None] = {
    "ping": None,
    "get_app_info": None,
    "get_resource_stats": None,
    "get_data_dir_info": None,
    "get_block_registry": "catalog",
    "get_user_blocks_dir": "catalog",
    "list_user_block_files": "catalog",
    "run_block": "run_block",
    "run_flow": "run_flow",
    "pause_flow": "run_flow",
    "resume_flow": "run_flow",
    "continue_flow": "run_flow",
    "stop_flow": "run_flow",
    "force_reset": "run_flow",
    "step_flow": "run_flow",
    "set_breakpoints": "run_flow",
    "validate_flow": None,
    "is_running": None,
    "drain_ui_events": None,
    "list_flows": "flows",
    "load_flow": "flows",
    "save_flow": "flows",
    "delete_flow": "flows",
    "rename_flow": "flows",
    "duplicate_flow": "flows",
    "list_schedule_jobs": "schedules",
    "remove_schedule_job": "schedules",
    "get_run_log_info": "runs",
    "export_run_log": "runs",
    "get_ui_settings": None,
    "set_ui_settings": None,
    "get_hotkeys": None,
    "set_hotkeys": None,
    "set_diag_logging": None,
    "get_diag_logging": None,
    "get_notice_read_id": None,
    "set_notice_read_id": None,
    "mcp_get_status": None,
    "browser_status": None,
    "log_audit": None,
    "log_system": None,
    "fetch_announcement": None,
    "fetch_notice": None,
    "check_for_update": None,
    "read_local_image": "flows",
    "capture_desktop": None,
}

# MCP 工具（/rpc）→ 所需 scope；None = 任意已认证身份；不在表内 = 仅主密钥
TOOL_SCOPES: dict[str, str | None] = {
    "get_status": None,
    "list_blocks": "catalog",
    "get_block_schema": "catalog",
    "list_flows": "flows",
    "list_schedules": "schedules",
    "recent_runs": "runs",
    "run_block": "run_block",
    "run_flow": "run_flow",
    "flow_control": "run_flow",
    "capture_screen": None,
    "locate_text_on_screen": None,
    "reset_session": "run_block",
}


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _keys_from_config() -> list[dict[str, Any]]:
    from backend.paths import load_app_config

    raw = load_app_config().get("api_keys")
    return [k for k in raw if isinstance(k, dict)] if isinstance(raw, list) else []


def _save_keys(keys: list[dict[str, Any]]) -> None:
    from backend.paths import load_app_config, save_app_config

    cfg = load_app_config()
    cfg["api_keys"] = keys
    save_app_config(cfg)


# ---------------------------------------------------------------------------
# CRUD（主密钥侧）
# ---------------------------------------------------------------------------

def create_key(
    name: str,
    scopes: list[str],
    block_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """签发新 Key。返回值含明文 key（仅此一次）；存储只留哈希。"""
    clean_scopes = [s for s in (str(x).strip() for x in scopes or []) if s in SCOPES]
    allowlist = sorted(
        {str(x).strip() for x in (block_allowlist or []) if str(x).strip()}
    )
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    record = {
        "id": "k" + secrets.token_hex(6),
        "name": str(name or "").strip()[:60] or "未命名凭证",
        "key_hash": _hash_key(raw),
        "key_prefix": raw[:10],
        "scopes": clean_scopes,
        "block_allowlist": allowlist,
        "enabled": True,
        "created_at": int(time.time()),
        "last_used_at": None,
    }
    keys = _keys_from_config()
    keys.append(record)
    _save_keys(keys)
    return {**{k: v for k, v in record.items() if k != "key_hash"}, "key": raw}


def list_keys() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in rec.items() if k != "key_hash"} for rec in _keys_from_config()
    ]


def update_key(key_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    keys = _keys_from_config()
    for rec in keys:
        if rec.get("id") == str(key_id):
            if isinstance(patch.get("scopes"), list):
                rec["scopes"] = [s for s in map(str, patch["scopes"]) if s in SCOPES]
            if isinstance(patch.get("block_allowlist"), list):
                rec["block_allowlist"] = sorted(
                    {str(x).strip() for x in patch["block_allowlist"] if str(x).strip()}
                )
            if isinstance(patch.get("enabled"), bool):
                rec["enabled"] = patch["enabled"]
            if isinstance(patch.get("name"), str) and patch["name"].strip():
                rec["name"] = patch["name"].strip()[:60]
            _save_keys(keys)
            return {"ok": True, "key": {k: v for k, v in rec.items() if k != "key_hash"}}
    return {"ok": False, "error": f"未找到密钥: {key_id}"}


def delete_key(key_id: str) -> dict[str, Any]:
    keys = _keys_from_config()
    remain = [rec for rec in keys if rec.get("id") != str(key_id)]
    if len(remain) == len(keys):
        return {"ok": False, "error": f"未找到密钥: {key_id}"}
    _save_keys(remain)
    return {"ok": True, "deleted": str(key_id)}


# ---------------------------------------------------------------------------
# 认证（请求侧）
# ---------------------------------------------------------------------------

def authenticate(bearer: str) -> dict[str, Any] | None:
    """校验一个 API Key 明文。命中且启用 → 返回该记录（含 scopes / allowlist）；
    否则 None（未命中或已停用）。"""
    bearer = str(bearer or "").strip()
    if not bearer.startswith(KEY_PREFIX):
        return None
    digest = _hash_key(bearer)
    for rec in _keys_from_config():
        stored = str(rec.get("key_hash") or "")
        if rec.get("enabled") and stored and hmac.compare_digest(stored, digest):
            rec = {**rec, "last_used_at": int(time.time())}
            # last_used_at 静默回写，失败不影响请求
            try:
                keys = _keys_from_config()
                for r in keys:
                    if r.get("id") == rec["id"]:
                        r["last_used_at"] = rec["last_used_at"]
                _save_keys(keys)
            except Exception:
                pass
            return rec
    return None


def identity_scopes(identity: dict[str, Any] | None) -> set[str] | None:
    """身份的 scope 集合；None = 主密钥（全权）。"""
    if identity is None:
        return None
    return set(identity.get("scopes") or [])


def identity_allowlist(identity: dict[str, Any] | None) -> list[str]:
    if identity is None:
        return []
    return [str(x) for x in (identity.get("block_allowlist") or [])]


def method_allowed(identity: dict[str, Any] | None, method: str) -> bool:
    """主密钥全权；API Key 按 METHOD_SCOPES 判定（未登记方法 = 仅主密钥）。"""
    scopes = identity_scopes(identity)
    if scopes is None:
        return True
    required = METHOD_SCOPES.get(method, "__admin_only__")
    return required is not None and required in scopes


def tool_allowed(identity: dict[str, Any] | None, tool: str) -> bool:
    scopes = identity_scopes(identity)
    if scopes is None:
        return True
    required = TOOL_SCOPES.get(tool, "__admin_only__")
    return required is not None and required in scopes


def block_allowed(identity: dict[str, Any] | None, block_type: str) -> bool:
    allowlist = identity_allowlist(identity)
    return not allowlist or str(block_type or "").strip() in allowlist


def flow_allowlist_floor(identity: dict[str, Any] | None, node_types: set[str]) -> list[str]:
    """流程级静态检查：白名单非空时，返回流程内越界（且非管道类）的积木类型；
    空集表示无额外限制。管道豁免与解释器 allow_only 闸同口径。"""
    allowlist = identity_allowlist(identity)
    if not allowlist:
        return []
    from backend.core.execution_policy import PLUMBING_TYPES

    allow = set(allowlist)
    return sorted(
        {t for t in node_types if str(t).strip() not in allow and str(t).strip() not in PLUMBING_TYPES}
    )
