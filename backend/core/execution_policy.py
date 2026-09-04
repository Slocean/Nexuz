"""Single source of truth for risky flow capabilities and runtime policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CAPABILITY_LABELS = {
    "python_script": "Python 脚本（可信代码）",
    "run_command": "执行系统命令",
    "file_io": "文件读写",
    "file_manage": "文件整理（移动/复制/重命名）",
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
        "file_manage",
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


# 外部 AI（MCP）执行的策略下限：危险命令类无论流程自身策略如何一律拒绝。
# power_action（关机/重启）影响整机，与 run_block 的硬拒口径保持一致。
MCP_FLOOR_DENY = frozenset(CRITICAL_TYPES | {"power_action"})


def mcp_policy_floor() -> dict[str, Any]:
    """__policy_floor__ 流程标记的内容：mode 提到 standard + 危险命令类硬拒。

    该标记随流程字典传播（call_subflow 的 {**flow} 展开、定时任务快照），
    由 interpreter._execute / scheduler 预扫描统一套用。
    """
    return {"deny": sorted(MCP_FLOOR_DENY), "mode_min": "standard"}


def merge_policy_floors(primary: Any, secondary: Any) -> dict[str, Any] | None:
    """合并两个下限标记（deny 并集、mode_min 就严），用于父子流程传递。

    子流程文件自带更弱的标记时，父流程的下限仍然生效——标记只能加严。
    """
    floors = [f for f in (primary, secondary) if isinstance(f, dict)]
    if not floors:
        return None
    deny: set[str] = set()
    mode_min = ""
    for floor in floors:
        deny.update(str(t).strip() for t in (floor.get("deny") or []) if str(t).strip())
        if str(floor.get("mode_min") or "").strip().lower() == "standard":
            mode_min = "standard"
    return {"deny": sorted(deny), "mode_min": mode_min}


def apply_policy_floor(policy: ExecutionPolicy, floor: Any) -> ExecutionPolicy:
    """把下限合并进策略：denylist 取并集；mode 只升不降（standard 下限压过 legacy）。

    流程自带字段无法削弱下限（外部传入的标记也只能加严），因此来源不可信的
    流程可以安全携带该标记。
    """
    if not isinstance(floor, dict):
        return policy
    deny = frozenset(
        str(t).strip() for t in (floor.get("deny") or []) if str(t).strip()
    )
    mode = policy.mode
    if str(floor.get("mode_min") or "").strip().lower() == "standard" and mode == "legacy":
        mode = "standard"
    if not deny and mode == policy.mode:
        return policy
    return ExecutionPolicy(
        mode=mode,
        allowlist=policy.allowlist,
        denylist=policy.denylist | deny,
        source=policy.source + "+floor",
    )


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
