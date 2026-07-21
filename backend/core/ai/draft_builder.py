"""FlowModel draft mutations for AI orchestration."""

from __future__ import annotations

import copy
import uuid
from typing import Any

EDGE_KEYS = ("next", "then", "else", "body", "catch", "finally")
GEOMETRIC_PARAM_KEYS = frozenset(
    {"x", "y", "points", "region", "from_x", "from_y", "to_x", "to_y"}
)


def empty_draft(*, name: str = "AI 草稿") -> dict[str, Any]:
    return {
        "flow_id": f"ai-draft-{uuid.uuid4().hex[:12]}",
        "name": name,
        "version": 1,
        "variables": {},
        "variable_schemas": {},
        "nodes": {},
        "entry": None,
        "breakpoints": [],
    }


def clone_flow(flow: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(flow, dict):
        return empty_draft()
    draft = copy.deepcopy(flow)
    if not isinstance(draft.get("nodes"), dict):
        draft["nodes"] = {}
    if "entry" not in draft:
        draft["entry"] = None
    if "variables" not in draft or not isinstance(draft["variables"], dict):
        draft["variables"] = {}
    if "flow_id" not in draft or not draft["flow_id"]:
        draft["flow_id"] = f"ai-draft-{uuid.uuid4().hex[:12]}"
    if "name" not in draft:
        draft["name"] = "AI 草稿"
    if "version" not in draft:
        draft["version"] = 1
    return draft


def _new_node_id(nodes: dict[str, Any], prefix: str = "node") -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in (prefix or "node"))[:24]
    for _ in range(50):
        nid = f"{safe}_{uuid.uuid4().hex[:8]}"
        if nid not in nodes:
            return nid
    return f"{safe}_{uuid.uuid4().hex}"


def draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    items = []
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        items.append(
            {
                "id": nid,
                "type": node.get("type"),
                "label": (node.get("params") or {}).get("label")
                if isinstance(node.get("params"), dict)
                else None,
                "next": node.get("next"),
                "then": node.get("then"),
                "else": node.get("else"),
                "body": node.get("body"),
                "unverified_coords": bool(node.get("_ai_unverified_coords")),
            }
        )
    return {
        "flow_id": draft.get("flow_id"),
        "name": draft.get("name"),
        "entry": draft.get("entry"),
        "node_count": len(items),
        "nodes": items,
    }


def add_node(
    draft: dict[str, Any],
    *,
    block_type: str,
    params: dict[str, Any] | None = None,
    node_id: str | None = None,
    position: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    nodes = draft.setdefault("nodes", {})
    if not isinstance(nodes, dict):
        draft["nodes"] = {}
        nodes = draft["nodes"]

    nid = (node_id or "").strip() or _new_node_id(nodes, block_type)
    if nid in nodes:
        raise ValueError(f"节点已存在: {nid}")

    node: dict[str, Any] = {
        "type": block_type,
        "params": dict(params or {}),
        "next": None,
    }
    if position and isinstance(position, dict):
        node["position"] = {
            "x": float(position.get("x") or 0),
            "y": float(position.get("y") or 0),
        }
    else:
        # Auto-layout: stagger by node count
        idx = len(nodes)
        node["position"] = {"x": 120.0 + (idx % 4) * 220.0, "y": 120.0 + (idx // 4) * 140.0}
    if extra:
        node.update(extra)

    nodes[nid] = node
    if not draft.get("entry"):
        draft["entry"] = nid
    return draft, nid


def update_node(
    draft: dict[str, Any],
    node_id: str,
    *,
    params: dict[str, Any] | None = None,
    merge_params: bool = True,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    node = nodes.get(node_id)
    if not isinstance(node, dict):
        raise ValueError(f"节点不存在: {node_id}")
    if params is not None:
        if merge_params and isinstance(node.get("params"), dict):
            node["params"] = {**node["params"], **params}
        else:
            node["params"] = dict(params)
    if patch:
        for k, v in patch.items():
            if k in ("type", "params"):
                continue
            node[k] = v
    return draft


def remove_node(draft: dict[str, Any], node_id: str) -> dict[str, Any]:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if node_id not in nodes:
        raise ValueError(f"节点不存在: {node_id}")
    del nodes[node_id]
    if draft.get("entry") == node_id:
        draft["entry"] = next(iter(nodes.keys()), None)

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        for key in EDGE_KEYS:
            if node.get(key) == node_id:
                node[key] = None
        cases = node.get("cases")
        if isinstance(cases, list):
            for case in cases:
                if isinstance(case, dict) and case.get("next") == node_id:
                    case["next"] = None
    return draft


def connect(
    draft: dict[str, Any],
    *,
    from_id: str,
    to_id: str | None,
    edge: str = "next",
) -> dict[str, Any]:
    edge = (edge or "next").strip()
    if edge not in EDGE_KEYS:
        raise ValueError(f"不支持的边类型: {edge}（允许: {', '.join(EDGE_KEYS)}）")
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if from_id not in nodes:
        raise ValueError(f"起始节点不存在: {from_id}")
    if to_id is not None and to_id not in nodes:
        raise ValueError(f"目标节点不存在: {to_id}")
    node = nodes[from_id]
    if not isinstance(node, dict):
        raise ValueError(f"节点无效: {from_id}")
    node[edge] = to_id
    return draft


def set_entry(draft: dict[str, Any], node_id: str | None) -> dict[str, Any]:
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if node_id is not None and node_id not in nodes:
        raise ValueError(f"入口节点不存在: {node_id}")
    draft["entry"] = node_id
    return draft


def diff_nodes(base: dict[str, Any] | None, draft: dict[str, Any] | None) -> dict[str, Any]:
    base_nodes = (base or {}).get("nodes") if isinstance((base or {}).get("nodes"), dict) else {}
    draft_nodes = (draft or {}).get("nodes") if isinstance((draft or {}).get("nodes"), dict) else {}
    base_ids = set(base_nodes.keys())
    draft_ids = set(draft_nodes.keys())
    added = sorted(draft_ids - base_ids)
    removed = sorted(base_ids - draft_ids)
    changed = []
    for nid in sorted(base_ids & draft_ids):
        if base_nodes.get(nid) != draft_nodes.get(nid):
            changed.append(nid)
    return {
        "added": [
            {"id": i, "type": (draft_nodes.get(i) or {}).get("type")} for i in added
        ],
        "removed": [
            {"id": i, "type": (base_nodes.get(i) or {}).get("type")} for i in removed
        ],
        "changed": [
            {"id": i, "type": (draft_nodes.get(i) or {}).get("type")} for i in changed
        ],
        "entry_changed": (base or {}).get("entry") != (draft or {}).get("entry"),
    }


def is_binding_expr(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    return "{{" in s and "}}" in s


def params_need_coord_refs(params: dict[str, Any] | None) -> list[str]:
    """Return geometric keys that are raw numbers (not bindings)."""
    if not isinstance(params, dict):
        return []
    flagged: list[str] = []
    for key in GEOMETRIC_PARAM_KEYS:
        if key not in params:
            continue
        val = params[key]
        if val is None:
            continue
        if is_binding_expr(val):
            continue
        if key == "points" and isinstance(val, list):
            # list of points — treat non-empty as needing verification unless empty
            if val:
                flagged.append(key)
            continue
        if key == "region" and (isinstance(val, list) or isinstance(val, dict)):
            flagged.append(key)
            continue
        if isinstance(val, (int, float)) or (
            isinstance(val, str) and val.strip().lstrip("-").replace(".", "", 1).isdigit()
        ):
            flagged.append(key)
    return flagged
