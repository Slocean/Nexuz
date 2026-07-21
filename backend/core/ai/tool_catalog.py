"""SCHEMA → OpenAI tool definitions + block catalog helpers."""

from __future__ import annotations

from typing import Any

from backend.core.registry import BLOCK_REGISTRY, get_schemas

# Default denied for AI draft_add_node (can be overridden via allow_dangerous).
DEFAULT_DENIED_BLOCKS = frozenset(
    {
        "run_command",
        "python_script",
    }
)

# Require explicit allowlist even when allow_dangerous is on for file_io.
SENSITIVE_BLOCKS = frozenset({"file_io", "run_command", "python_script"})


def is_block_allowed(
    block_type: str,
    *,
    allow_dangerous: bool = False,
    allowlist: set[str] | frozenset[str] | None = None,
) -> bool:
    t = (block_type or "").strip()
    if not t:
        return False
    if allowlist is not None and t in allowlist:
        return True
    if t in DEFAULT_DENIED_BLOCKS and not allow_dangerous:
        return False
    if t == "file_io" and not allow_dangerous:
        return False
    return t in BLOCK_REGISTRY


def _input_to_json_schema(inp: dict[str, Any]) -> dict[str, Any]:
    name = str(inp.get("name") or "")
    itype = str(inp.get("type") or "string")
    desc_parts = [str(inp.get("label") or name)]
    if inp.get("placeholder"):
        desc_parts.append(f"示例: {inp['placeholder']}")
    prop: dict[str, Any] = {"description": "；".join(desc_parts)}

    if itype == "number":
        prop["type"] = ["number", "string"]
    elif itype == "boolean":
        prop["type"] = ["boolean", "string"]
    elif itype == "select":
        options = inp.get("options") or []
        prop["type"] = "string"
        if options:
            prop["enum"] = [str(o) for o in options]
    elif itype in ("rect", "point_list", "object", "array"):
        prop["type"] = ["object", "array", "string", "null"]
    else:
        prop["type"] = ["string", "number", "boolean", "object", "array", "null"]

    if inp.get("bindable"):
        prop["description"] += "（可绑定 {{变量}}）"
    return prop


def schema_to_short(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": schema.get("type"),
        "label": schema.get("label"),
        "category": schema.get("category"),
        "description": schema.get("description")
        or f"{schema.get('label') or schema.get('type')}（{schema.get('category') or ''}）",
    }


def list_blocks(
    *,
    category: str | None = None,
    allow_dangerous: bool = False,
    allowlist: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    cat = (category or "").strip()
    out: list[dict[str, Any]] = []
    for schema in get_schemas():
        btype = str(schema.get("type") or "")
        if not is_block_allowed(btype, allow_dangerous=allow_dangerous, allowlist=allowlist):
            continue
        if cat and str(schema.get("category") or "") != cat:
            continue
        out.append(schema_to_short(schema))
    out.sort(key=lambda x: (str(x.get("category") or ""), str(x.get("type") or "")))
    return out


def get_block_schema(
    block_type: str,
    *,
    allow_dangerous: bool = False,
    allowlist: set[str] | frozenset[str] | None = None,
) -> dict[str, Any] | None:
    entry = BLOCK_REGISTRY.get(block_type)
    if not entry:
        return None
    if not is_block_allowed(block_type, allow_dangerous=allow_dangerous, allowlist=allowlist):
        return {"error": f"积木 {block_type} 不在 AI 允许列表中"}
    schema = entry["schema"]
    inputs = []
    for inp in schema.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        inputs.append(
            {
                "name": inp.get("name"),
                "type": inp.get("type"),
                "label": inp.get("label"),
                "default": inp.get("default"),
                "options": inp.get("options"),
                "bindable": inp.get("bindable"),
                "required": inp.get("required"),
                "show_when": inp.get("show_when"),
                "json_schema": _input_to_json_schema(inp),
            }
        )
    return {
        "type": schema.get("type"),
        "label": schema.get("label"),
        "category": schema.get("category"),
        "inputs": inputs,
        "outputs": schema.get("outputs") or [],
    }


def openai_tools() -> list[dict[str, Any]]:
    """Fixed set of orchestration + perception tools (OpenAI function calling format)."""
    defs = [
        {
            "name": "list_blocks",
            "description": "按分类列出可用积木（type/label/简述）。编排前先调用以了解平台能力。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "可选，过滤分类：动作类/识别类/控制类/系统类等",
                    }
                },
            },
        },
        {
            "name": "get_block_schema",
            "description": "获取单个积木的完整 inputs 定义，再据此填写 draft_add_node 的 params。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "积木 type，如 click、delay"},
                },
                "required": ["type"],
            },
        },
        {
            "name": "draft_add_node",
            "description": "向草稿添加节点。坐标类字段不要臆造数字，应使用变量绑定或 point_ref。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "params": {"type": "object"},
                    "node_id": {"type": "string", "description": "可选自定义节点 id"},
                    "position": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                    },
                    "point_ref": {
                        "type": "string",
                        "description": "若本节点需要坐标，引用 artifacts.points 中的 ref_id",
                    },
                },
                "required": ["type"],
            },
        },
        {
            "name": "draft_update_node",
            "description": "更新草稿节点的 params 或边字段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "params": {"type": "object"},
                    "merge_params": {"type": "boolean", "default": True},
                    "point_ref": {"type": "string"},
                    "next": {"type": ["string", "null"]},
                    "then": {"type": ["string", "null"]},
                    "else": {"type": ["string", "null"]},
                    "body": {"type": ["string", "null"]},
                },
                "required": ["node_id"],
            },
        },
        {
            "name": "draft_remove_node",
            "description": "删除草稿节点并清理指向它的边。",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        },
        {
            "name": "draft_connect",
            "description": "连接两个节点：edge 为 next/then/else/body/catch/finally。",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_id": {"type": "string"},
                    "to_id": {"type": ["string", "null"]},
                    "edge": {
                        "type": "string",
                        "enum": ["next", "then", "else", "body", "catch", "finally"],
                        "default": "next",
                    },
                },
                "required": ["from_id", "to_id"],
            },
        },
        {
            "name": "draft_set_entry",
            "description": "设置流程入口节点。",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": ["string", "null"]}},
                "required": ["node_id"],
            },
        },
        {
            "name": "draft_get",
            "description": "返回当前草稿摘要，防止上下文漂移。",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "capture_screen",
            "description": "截取虚拟桌面，供后续 OCR 定位。返回截图句柄与尺寸（不含完整像素）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hide_window": {
                        "type": "boolean",
                        "default": True,
                        "description": "截图前是否隐藏 Nexuz 主窗",
                    }
                },
            },
        },
        {
            "name": "locate_text_on_screen",
            "description": "在最近截图或全屏上用 OCR 查找文字，返回中心点 ref_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_text": {"type": "string"},
                    "match_mode": {
                        "type": "string",
                        "enum": ["contains", "exact", "regex"],
                        "default": "contains",
                    },
                    "shot_ref": {
                        "type": "string",
                        "description": "可选，capture_screen 返回的 shot_id；默认用最近一张",
                    },
                    "label": {"type": "string", "description": "点位可读标签"},
                },
                "required": ["match_text"],
            },
        },
        {
            "name": "pack_point",
            "description": "把绝对屏幕坐标打包为与人工取点一致的结构，写入 artifacts.points。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "label": {"type": "string"},
                    "source": {"type": "string", "default": "manual"},
                },
                "required": ["x", "y"],
            },
        },
        {
            "name": "bind_point_to_node",
            "description": "将 artifacts 中的点写入指定 click/hover/drag 等节点的坐标 params。",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "point_ref": {"type": "string"},
                    "fields": {
                        "type": "object",
                        "description": "可选字段映射，默认写入 x/y 及 packed 元数据",
                    },
                },
                "required": ["node_id", "point_ref"],
            },
        },
    ]
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["parameters"],
            },
        }
        for d in defs
    ]
