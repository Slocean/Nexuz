"""Single source of truth for risky flow capabilities and runtime policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CAPABILITY_LABELS = {
    "python_script": "Python 脚本（可信代码）",
    "run_command": "执行系统命令",
    "file_io": "文件读写",
    "http_request": "HTTP / 网络请求",
    "clipboard": "剪贴板访问",
    "call_subflow": "调用子流程",
    "window_close": "关闭窗口或进程",
    "schedule_trigger": "定时执行",
    "frida": "Frida 进程操作",
    "process_kill": "结束进程",
    "power_action": "电源操作（关机/重启等）",
    "zip_archive": "压缩/解压（文件写入）",
    "open_path": "打开文件/网址（可启动程序）",
}

CRITICAL_TYPES = frozenset({"python_script", "run_command"})
ELEVATED_TYPES = frozenset(
    {
        "file_io",
        "http_request",
        "clipboard",
        "call_subflow",
        "window_close",
        "schedule_trigger",
        "process_kill",
        "power_action",
        "zip_archive",
        "open_path",
    }
)
HIGH_RISK_TYPES = frozenset(CRITICAL_TYPES | ELEVATED_TYPES)


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str
    allowlist: frozenset[str] = frozenset()
    denylist: frozenset[str] = frozenset()
    source: str = "flow"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "allowlist": sorted(self.allowlist),
            "denylist": sorted(self.denylist),
            "source": self.source,
        }


class ExecutionPolicyError(PermissionError):
    def __init__(self, violation: dict[str, Any], policy: ExecutionPolicy):
        self.violation = violation
        self.policy = policy
        super().__init__(
            "执行策略拒绝积木 "
            f"{violation.get('block_type')}（节点 {violation.get('node_id')}，"
            f"模式 {policy.mode}）"
        )


def resolve_execution_policy(flow: dict[str, Any]) -> ExecutionPolicy:
    raw = flow.get("execution_policy")
    if raw is None:
        # Existing flows keep their historical behavior. New flows explicitly
        # declare safe mode in the frontend model.
        return ExecutionPolicy(mode="legacy", source="legacy")
    if isinstance(raw, str):
        raw = {"mode": raw}
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode") or "safe").strip().lower()
    if mode in {"off", "all", "unrestricted"}:
        mode = "legacy"
    if mode not in {"safe", "standard", "legacy"}:
        mode = "safe"
    allowlist = frozenset(
        str(item).strip()
        for item in (raw.get("allowlist") or [])
        if str(item).strip()
    )
    denylist = frozenset(
        str(item).strip()
        for item in (raw.get("denylist") or [])
        if str(item).strip()
    )
    return ExecutionPolicy(
        mode=mode,
        allowlist=allowlist,
        denylist=denylist,
        source="flow",
    )


def _risk_for_node(block_type: str, node: dict[str, Any]) -> tuple[str, str] | None:
    if block_type in CRITICAL_TYPES:
        return "critical", CAPABILITY_LABELS[block_type]
    if block_type in ELEVATED_TYPES:
        return "elevated", CAPABILITY_LABELS[block_type]

    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    capture_mode = str(params.get("capture_mode") or "").strip().lower()
    if block_type in {"click", "drag", "mouse_hover"} and capture_mode == "frida_ui":
        return "elevated", CAPABILITY_LABELS["frida"]

    try:
        from backend.core.registry import BLOCK_REGISTRY

        entry = BLOCK_REGISTRY.get(block_type)
        schema = entry.get("schema") if isinstance(entry, dict) else None
        if isinstance(schema, dict) and schema.get("trust_tier") == "user_plugin":
            return "critical", "自定义积木（可信插件）"
    except Exception:
        pass
    return None


def check_node_allowed(
    policy: ExecutionPolicy,
    node_id: str,
    node: dict[str, Any],
) -> dict[str, Any] | None:
    block_type = str(node.get("type") or "").strip()
    risk = _risk_for_node(block_type, node)
    if block_type in policy.denylist:
        tier, label = risk or ("policy", block_type)
    elif block_type in policy.allowlist:
        return None
    elif policy.mode == "legacy" or risk is None:
        return None
    elif policy.mode == "standard" and risk[0] != "critical":
        return None
    else:
        tier, label = risk
    return {
        "node_id": str(node_id),
        "block_type": block_type,
        "tier": tier,
        "label": label,
    }


def scan_flow_violations(
    flow: dict[str, Any],
    policy: ExecutionPolicy | None = None,
) -> list[dict[str, Any]]:
    effective = policy or resolve_execution_policy(flow)
    nodes = flow.get("nodes")
    if not isinstance(nodes, dict):
        return []
    violations: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or node.get("disabled"):
            continue
        violation = check_node_allowed(effective, str(node_id), node)
        if violation:
            violations.append(violation)
    return violations
