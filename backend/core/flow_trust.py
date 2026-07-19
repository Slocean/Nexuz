"""Static capability summary for external flows before they enter the library."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

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
}

HIGH_RISK_TYPES = frozenset(CAPABILITY_LABELS)


def analyze_flow_risks(
    flow: dict[str, Any],
    *,
    known_types: Iterable[str] = (),
    trusted_plugin_types: Iterable[str] = (),
) -> dict[str, Any]:
    known = {str(item) for item in known_types}
    plugins = {str(item) for item in trusted_plugin_types}
    counts: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    if isinstance(nodes, dict):
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            block_type = str(node.get("type") or "").strip()
            if not block_type:
                continue
            if block_type in HIGH_RISK_TYPES:
                counts[block_type] += 1
            elif block_type in plugins:
                counts[block_type] += 1
            if known and block_type not in known:
                unknown[block_type] += 1

    capabilities = [
        {
            "type": block_type,
            "label": CAPABILITY_LABELS.get(block_type, "自定义积木（可信插件）"),
            "count": count,
        }
        for block_type, count in sorted(counts.items())
    ]
    unknown_types = [
        {"type": block_type, "count": count}
        for block_type, count in sorted(unknown.items())
    ]
    return {
        "needs_strong_warning": bool(capabilities or unknown_types),
        "capabilities": capabilities,
        "unknown_types": unknown_types,
    }
