"""Dispatch AI tools against session draft + artifacts."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from backend.core.ai import draft_builder
from backend.core.ai import locate as locate_mod
from backend.core.ai.tool_catalog import (
    get_block_schema,
    is_block_allowed,
    list_blocks,
)

CaptureFn = Callable[..., dict[str, Any]]


_TOOL_LABELS = {
    "list_blocks": "查看积木目录",
    "get_block_schema": "读取积木参数",
    "draft_add_node": "添加节点",
    "draft_update_node": "更新节点",
    "draft_remove_node": "删除节点",
    "draft_connect": "连接节点",
    "draft_set_entry": "设置入口",
    "draft_get": "查看草稿",
    "capture_screen": "截取屏幕",
    "locate_text_on_screen": "OCR 文字定位",
    "pack_point": "打包坐标",
    "bind_point_to_node": "绑定点位到节点",
}


def _tool_result_summary(name: str, result: dict[str, Any]) -> str:
    if not result.get("ok", True) and result.get("error"):
        return str(result["error"])[:160]
    if name == "list_blocks":
        return f"共 {result.get('count', 0)} 个积木"
    if name == "get_block_schema":
        schema = result.get("schema") or {}
        return f"{schema.get('label') or schema.get('type') or 'schema'}"
    if name == "draft_add_node":
        return f"已添加 {result.get('type')}（{result.get('node_id')}）"
    if name == "draft_update_node":
        return f"已更新 {result.get('node_id')}"
    if name == "draft_remove_node":
        return f"已删除 {result.get('removed')}"
    if name == "draft_connect":
        return "已连线"
    if name == "draft_set_entry":
        return f"入口 → {result.get('entry')}"
    if name == "draft_get":
        summary = result.get("summary") or {}
        return f"草稿 {summary.get('node_count', 0)} 节点"
    if name == "capture_screen":
        return f"截图 {result.get('width')}×{result.get('height')}（{result.get('shot_id')}）"
    if name == "locate_text_on_screen":
        return (
            f"命中「{result.get('matched_text')}」→ ({result.get('x')},{result.get('y')}) "
            f"ref={result.get('point_ref')}"
        )
    if name == "pack_point":
        return f"点 ({result.get('x')},{result.get('y')}) ref={result.get('point_ref')}"
    if name == "bind_point_to_node":
        return f"{result.get('point_ref')} → 节点 {result.get('node_id')}"
    return "完成"


def _args_brief(name: str, args: dict[str, Any]) -> str:
    if not args:
        return ""
    if name == "draft_add_node":
        parts = [str(args.get("type") or "")]
        if args.get("node_id"):
            parts.append(f"id={args['node_id']}")
        params = args.get("params") if isinstance(args.get("params"), dict) else {}
        if params.get("text"):
            parts.append(f"text={params['text']!r}")
        if params.get("ms") is not None:
            parts.append(f"ms={params['ms']}")
        if args.get("point_ref"):
            parts.append(f"point_ref={args['point_ref']}")
        return " ".join(p for p in parts if p)
    if name == "draft_connect":
        return f"{args.get('from_id')} -{args.get('edge') or 'next'}→ {args.get('to_id')}"
    if name == "locate_text_on_screen":
        return f"「{args.get('match_text')}」 mode={args.get('match_mode') or 'contains'}"
    if name == "get_block_schema":
        return str(args.get("type") or "")
    if name == "list_blocks" and args.get("category"):
        return str(args.get("category"))
    if name == "bind_point_to_node":
        return f"{args.get('point_ref')} → {args.get('node_id')}"
    if name == "pack_point":
        return f"({args.get('x')},{args.get('y')})"
    # compact JSON
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        s = str(args)
    return s[:120]


class ToolRuntime:
    def __init__(
        self,
        *,
        capture_fn: CaptureFn | None = None,
        allow_dangerous: bool = False,
        allowlist: set[str] | None = None,
        strict_coords: bool = False,
    ):
        self.capture_fn = capture_fn
        self.allow_dangerous = allow_dangerous
        self.allowlist = allowlist
        self.strict_coords = strict_coords

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        *,
        draft: dict[str, Any],
        artifacts: dict[str, Any],
        tool_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        started = time.time()
        try:
            result = self._dispatch(name, args, draft=draft, artifacts=artifacts)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        entry = {
            "name": name,
            "arguments": args,
            "ok": bool(result.get("ok", True)) if isinstance(result, dict) else True,
            "error": (result.get("error") if isinstance(result, dict) else None),
            "elapsed_ms": int((time.time() - started) * 1000),
            "summary": _tool_result_summary(name, result if isinstance(result, dict) else {}),
        }
        tool_trace.append(entry)
        if not isinstance(result, dict):
            return {"ok": True, "result": result}
        return result

    def _dispatch(
        self,
        name: str,
        args: dict[str, Any],
        *,
        draft: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "list_blocks":
            blocks = list_blocks(
                category=args.get("category"),
                allow_dangerous=self.allow_dangerous,
                allowlist=self.allowlist,
            )
            return {"ok": True, "blocks": blocks, "count": len(blocks)}

        if name == "get_block_schema":
            btype = str(args.get("type") or "")
            schema = get_block_schema(
                btype,
                allow_dangerous=self.allow_dangerous,
                allowlist=self.allowlist,
            )
            if schema is None:
                return {"ok": False, "error": f"未知积木: {btype}"}
            if schema.get("error"):
                return {"ok": False, "error": schema["error"]}
            return {"ok": True, "schema": schema}

        if name == "draft_add_node":
            return self._draft_add_node(draft, artifacts, args)

        if name == "draft_update_node":
            return self._draft_update_node(draft, artifacts, args)

        if name == "draft_remove_node":
            nid = str(args.get("node_id") or "")
            draft_builder.remove_node(draft, nid)
            return {"ok": True, "removed": nid, "summary": draft_builder.draft_summary(draft)}

        if name == "draft_connect":
            draft_builder.connect(
                draft,
                from_id=str(args.get("from_id") or ""),
                to_id=args.get("to_id"),
                edge=str(args.get("edge") or "next"),
            )
            return {"ok": True, "summary": draft_builder.draft_summary(draft)}

        if name == "draft_set_entry":
            draft_builder.set_entry(draft, args.get("node_id"))
            return {"ok": True, "entry": draft.get("entry")}

        if name == "draft_get":
            return {"ok": True, "summary": draft_builder.draft_summary(draft)}

        if name == "capture_screen":
            if self.capture_fn is None:
                return {"ok": False, "error": "截图能力不可用"}
            hide = args.get("hide_window")
            hide_window = True if hide is None else bool(hide)
            cap = locate_mod.capture_to_artifact(self.capture_fn, hide_window=hide_window)
            if not cap.get("ok"):
                return {"ok": False, "error": cap.get("error") or "截图失败"}
            art = cap["artifact"]
            artifacts.setdefault("shots", {})[art["shot_id"]] = art
            return cap["model_view"]

        if name == "locate_text_on_screen":
            return locate_mod.locate_text(
                artifacts,
                match_text=str(args.get("match_text") or ""),
                match_mode=str(args.get("match_mode") or "contains"),
                shot_ref=args.get("shot_ref"),
                label=args.get("label"),
                capture_fn=self.capture_fn,
            )

        if name == "pack_point":
            return locate_mod.pack_point_artifact(
                artifacts,
                x=args.get("x") or 0,
                y=args.get("y") or 0,
                label=args.get("label"),
                source=str(args.get("source") or "manual"),
            )

        if name == "bind_point_to_node":
            return self._bind_point(draft, artifacts, args)

        return {"ok": False, "error": f"未知 tool: {name}"}

    def _resolve_point(
        self, artifacts: dict[str, Any], point_ref: str | None
    ) -> dict[str, Any] | None:
        if not point_ref:
            return None
        points = artifacts.get("points") if isinstance(artifacts.get("points"), dict) else {}
        pt = points.get(point_ref)
        return pt if isinstance(pt, dict) else None

    def _apply_point_ref(
        self,
        params: dict[str, Any],
        artifacts: dict[str, Any],
        point_ref: str | None,
    ) -> tuple[dict[str, Any], bool]:
        pt = self._resolve_point(artifacts, point_ref)
        if pt is None:
            return params, False
        return locate_mod.apply_point_to_params(pt, params), True

    def _check_coords(
        self, params: dict[str, Any], *, has_point_ref: bool
    ) -> dict[str, Any] | None:
        flagged = draft_builder.params_need_coord_refs(params)
        if not flagged:
            return None
        if has_point_ref:
            return None
        # Bindings already filtered in params_need_coord_refs
        if self.strict_coords:
            return {
                "ok": False,
                "error": (
                    f"坐标字段 {flagged} 必须通过 point_ref / 变量绑定写入，"
                    "禁止臆造数字。请先 locate_text_on_screen 或 pack_point。"
                ),
            }
        return None  # allow but caller marks unverified

    def _draft_add_node(
        self,
        draft: dict[str, Any],
        artifacts: dict[str, Any],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        btype = str(args.get("type") or "").strip()
        if not btype:
            return {"ok": False, "error": "缺少 type"}
        if not is_block_allowed(
            btype, allow_dangerous=self.allow_dangerous, allowlist=self.allowlist
        ):
            return {"ok": False, "error": f"积木不允许用于 AI 编排: {btype}"}

        params = dict(args.get("params") or {}) if isinstance(args.get("params"), dict) else {}
        point_ref = args.get("point_ref")
        params, bound = self._apply_point_ref(params, artifacts, point_ref)
        err = self._check_coords(params, has_point_ref=bound)
        if err:
            return err

        unverified = bool(draft_builder.params_need_coord_refs(params)) and not bound
        extra = {}
        if unverified:
            extra["_ai_unverified_coords"] = True

        draft, nid = draft_builder.add_node(
            draft,
            block_type=btype,
            params=params,
            node_id=args.get("node_id"),
            position=args.get("position") if isinstance(args.get("position"), dict) else None,
            extra=extra or None,
        )
        return {
            "ok": True,
            "node_id": nid,
            "type": btype,
            "unverified_coords": unverified,
            "summary": draft_builder.draft_summary(draft),
        }

    def _draft_update_node(
        self,
        draft: dict[str, Any],
        artifacts: dict[str, Any],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        nid = str(args.get("node_id") or "")
        params = args.get("params")
        point_ref = args.get("point_ref")
        merge = True if args.get("merge_params") is None else bool(args.get("merge_params"))

        patch = {}
        for edge in ("next", "then", "else", "body", "catch", "finally"):
            if edge in args:
                patch[edge] = args[edge]

        if isinstance(params, dict) or point_ref:
            use_params = dict(params) if isinstance(params, dict) else {}
            # If only point_ref, merge onto existing
            if point_ref and not isinstance(params, dict):
                nodes = draft.get("nodes") or {}
                node = nodes.get(nid) if isinstance(nodes, dict) else None
                use_params = dict((node or {}).get("params") or {})
            use_params, bound = self._apply_point_ref(use_params, artifacts, point_ref)
            err = self._check_coords(use_params, has_point_ref=bound)
            if err:
                return err
            unverified = bool(draft_builder.params_need_coord_refs(use_params)) and not bound
            draft_builder.update_node(
                draft, nid, params=use_params, merge_params=merge, patch=patch or None
            )
            if bound:
                node = (draft.get("nodes") or {}).get(nid)
                if isinstance(node, dict):
                    node.pop("_ai_unverified_coords", None)
            elif unverified:
                node = (draft.get("nodes") or {}).get(nid)
                if isinstance(node, dict):
                    node["_ai_unverified_coords"] = True
        elif patch:
            draft_builder.update_node(draft, nid, patch=patch)
        else:
            return {"ok": False, "error": "无更新内容"}

        return {"ok": True, "node_id": nid, "summary": draft_builder.draft_summary(draft)}

    def _bind_point(
        self,
        draft: dict[str, Any],
        artifacts: dict[str, Any],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        nid = str(args.get("node_id") or "")
        pref = str(args.get("point_ref") or "")
        pt = self._resolve_point(artifacts, pref)
        if pt is None:
            return {"ok": False, "error": f"点位不存在: {pref}"}
        nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
        node = nodes.get(nid)
        if not isinstance(node, dict):
            return {"ok": False, "error": f"节点不存在: {nid}"}
        params = locate_mod.apply_point_to_params(pt, node.get("params") or {})
        if isinstance(args.get("fields"), dict):
            params.update(args["fields"])
        node["params"] = params
        node.pop("_ai_unverified_coords", None)
        return {
            "ok": True,
            "node_id": nid,
            "point_ref": pref,
            "x": pt.get("x"),
            "y": pt.get("y"),
            "summary": draft_builder.draft_summary(draft),
        }


def tool_result_message(tool_call_id: str, name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": json.dumps(result, ensure_ascii=False, default=str),
    }


def assistant_tool_call_message(turn_content: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild OpenAI assistant message with tool_calls for the next round."""
    openai_calls = []
    for tc in tool_calls:
        raw = tc.get("raw") if isinstance(tc.get("raw"), dict) else None
        if raw:
            openai_calls.append(raw)
        else:
            openai_calls.append(
                {
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": json.dumps(
                            tc.get("arguments") or {}, ensure_ascii=False
                        ),
                    },
                }
            )
    return {
        "role": "assistant",
        "content": turn_content if turn_content else None,
        "tool_calls": openai_calls,
    }
