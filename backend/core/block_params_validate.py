"""Static Block parameter checks derived from registry SCHEMA metadata."""

from __future__ import annotations

import re
from typing import Any

from backend.core.registry import BLOCK_REGISTRY

_BINDING_RE = re.compile(r"\{\{[^}]+\}\}|\$[A-Za-z_][A-Za-z0-9_.]*")


def _is_binding(value: Any) -> bool:
    return isinstance(value, str) and bool(_BINDING_RE.search(value))


def _visible(inp: dict[str, Any], params: dict[str, Any]) -> bool:
    condition = inp.get("show_when")
    if not isinstance(condition, dict):
        return True
    for key, expected in condition.items():
        actual = params.get(key)
        if actual is None:
            actual = expected if isinstance(expected, bool) else ""
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif str(actual) != str(expected):
            return False
    return True


def _issue(
    node_id: str,
    block_type: str,
    code: str,
    message: str,
    *,
    param: str | None = None,
    level: str = "error",
) -> dict[str, Any]:
    result = {
        "level": level,
        "code": code,
        "node_id": node_id,
        "block_type": block_type,
        "message": message,
    }
    if param:
        result["param"] = param
    return result


def validate_flow_params(flow: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = flow.get("nodes")
    if not isinstance(nodes, dict):
        return []
    issues: list[dict[str, Any]] = []
    for raw_node_id, node in nodes.items():
        node_id = str(raw_node_id)
        if not isinstance(node, dict) or node.get("disabled"):
            continue
        block_type = str(node.get("type") or "").strip()
        entry = BLOCK_REGISTRY.get(block_type)
        if not isinstance(entry, dict):
            issues.append(
                _issue(
                    node_id,
                    block_type,
                    "unknown_block",
                    f"节点 {node_id} 使用未知积木：{block_type or '（空）'}",
                )
            )
            continue
        schema = entry.get("schema")
        inputs = schema.get("inputs") if isinstance(schema, dict) else None
        if not isinstance(inputs, list):
            continue
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        for inp in inputs:
            if not isinstance(inp, dict) or not _visible(inp, params):
                continue
            name = str(inp.get("name") or "").strip()
            if not name:
                continue
            value = params.get(name, inp.get("default"))
            label = str(inp.get("label") or name)
            if inp.get("required") and (value is None or value == "" or value == []):
                issues.append(
                    _issue(
                        node_id,
                        block_type,
                        "required",
                        f"节点 {node_id} 缺少必填参数：{label}",
                        param=name,
                    )
                )
                continue
            if value is None or value == "" or _is_binding(value):
                continue
            input_type = str(inp.get("type") or "string")
            valid = True
            if input_type == "number":
                try:
                    float(value)
                except (TypeError, ValueError):
                    valid = False
            elif input_type in {"boolean", "bool"}:
                valid = isinstance(value, bool) or str(value).lower() in {
                    "true",
                    "false",
                    "1",
                    "0",
                }
            elif input_type == "select":
                options = [str(item) for item in (inp.get("options") or [])]
                valid = not options or str(value) in options
                if not valid:
                    issues.append(
                        _issue(
                            node_id,
                            block_type,
                            "enum",
                            f"节点 {node_id} 的参数 {label} 不在允许值中",
                            param=name,
                        )
                    )
                    continue
            elif input_type in {"object", "keymap"}:
                valid = isinstance(value, dict)
            elif input_type in {"array", "point_list", "keys", "key_steps", "cases"}:
                valid = isinstance(value, list)
            if not valid:
                issues.append(
                    _issue(
                        node_id,
                        block_type,
                        "type",
                        f"节点 {node_id} 的参数 {label} 类型无效，期望 {input_type}",
                        param=name,
                    )
                )
    return issues
