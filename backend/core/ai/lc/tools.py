"""LangChain StructuredTool wrappers around ToolRuntime."""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.core.ai.tool_runtime import ToolRuntime

CaptureFn = Callable[..., dict[str, Any]]


class ToolSession:
    """Mutable bag passed into tool callables during a graph turn."""

    def __init__(
        self,
        *,
        draft: dict[str, Any],
        artifacts: dict[str, Any] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
        capture_fn: CaptureFn | None = None,
        allow_dangerous: bool = False,
        strict_coords: bool = True,
    ):
        self.draft = draft
        self.artifacts = artifacts if isinstance(artifacts, dict) else {"shots": {}, "points": {}}
        self.tool_trace = tool_trace if tool_trace is not None else []
        self.runtime = ToolRuntime(
            capture_fn=capture_fn,
            allow_dangerous=allow_dangerous,
            strict_coords=strict_coords,
        )

    def run(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.runtime.execute(
            name,
            arguments or {},
            draft=self.draft,
            artifacts=self.artifacts,
            tool_trace=self.tool_trace,
        )


def _json_result(result: dict[str, Any]) -> str:
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:8000]
    except Exception:
        return str(result)[:8000]


class ListBlocksArgs(BaseModel):
    category: str | None = Field(default=None, description="可选分类过滤")


class GetBlockSchemaArgs(BaseModel):
    type: str = Field(description="积木类型，如 delay / click")


class DraftAddNodeArgs(BaseModel):
    type: str = Field(description="积木类型")
    params: dict[str, Any] = Field(default_factory=dict)
    node_id: str | None = None
    point_ref: str | None = Field(default=None, description="定位得到的 point_ref")
    position: dict[str, Any] | None = None


class DraftUpdateNodeArgs(BaseModel):
    node_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    point_ref: str | None = None
    merge_params: bool = True


class DraftRemoveNodeArgs(BaseModel):
    node_id: str


class DraftConnectArgs(BaseModel):
    from_id: str
    to_id: str | None = None
    edge: str = "next"


class DraftSetEntryArgs(BaseModel):
    node_id: str | None = None


class CaptureScreenArgs(BaseModel):
    hide_window: bool = True


class LocateTextArgs(BaseModel):
    match_text: str
    match_mode: str = "contains"
    shot_ref: str | None = None
    label: str | None = None


class PackPointArgs(BaseModel):
    x: float
    y: float
    label: str | None = None
    source: str = "manual"


class BindPointArgs(BaseModel):
    point_ref: str
    node_id: str


class VisionLocateArgs(BaseModel):
    query: str = Field(description="要在截图中找的目标描述")
    shot_ref: str | None = Field(default=None, description="截图 id；默认最近一张")


class CallSkillArgs(BaseModel):
    skill_id: str = Field(description="技能 id，如 text_click / wechat_send_message")
    params: dict[str, Any] = Field(default_factory=dict)


def build_orchestration_tools(
    session: ToolSession,
    *,
    cfg: Any | None = None,
) -> list[StructuredTool]:
    """Tools bound to a live ToolSession (draft/artifacts mutated in place)."""

    def list_blocks(category: str | None = None) -> str:
        return _json_result(session.run("list_blocks", {"category": category}))

    def get_block_schema(type: str) -> str:  # noqa: A002
        return _json_result(session.run("get_block_schema", {"type": type}))

    def draft_add_node(
        type: str,  # noqa: A002
        params: dict[str, Any] | None = None,
        node_id: str | None = None,
        point_ref: str | None = None,
        position: dict[str, Any] | None = None,
    ) -> str:
        return _json_result(
            session.run(
                "draft_add_node",
                {
                    "type": type,
                    "params": params or {},
                    "node_id": node_id,
                    "point_ref": point_ref,
                    "position": position,
                },
            )
        )

    def draft_update_node(
        node_id: str,
        params: dict[str, Any] | None = None,
        point_ref: str | None = None,
        merge_params: bool = True,
    ) -> str:
        return _json_result(
            session.run(
                "draft_update_node",
                {
                    "node_id": node_id,
                    "params": params or {},
                    "point_ref": point_ref,
                    "merge_params": merge_params,
                },
            )
        )

    def draft_remove_node(node_id: str) -> str:
        return _json_result(session.run("draft_remove_node", {"node_id": node_id}))

    def draft_connect(from_id: str, to_id: str | None = None, edge: str = "next") -> str:
        return _json_result(
            session.run("draft_connect", {"from_id": from_id, "to_id": to_id, "edge": edge})
        )

    def draft_set_entry(node_id: str | None = None) -> str:
        return _json_result(session.run("draft_set_entry", {"node_id": node_id}))

    def draft_get() -> str:
        return _json_result(session.run("draft_get", {}))

    def capture_screen(hide_window: bool = True) -> str:
        return _json_result(session.run("capture_screen", {"hide_window": hide_window}))

    def locate_text_on_screen(
        match_text: str,
        match_mode: str = "contains",
        shot_ref: str | None = None,
        label: str | None = None,
    ) -> str:
        return _json_result(
            session.run(
                "locate_text_on_screen",
                {
                    "match_text": match_text,
                    "match_mode": match_mode,
                    "shot_ref": shot_ref,
                    "label": label,
                },
            )
        )

    def pack_point(
        x: float, y: float, label: str | None = None, source: str = "manual"
    ) -> str:
        return _json_result(
            session.run("pack_point", {"x": x, "y": y, "label": label, "source": source})
        )

    def bind_point_to_node(point_ref: str, node_id: str) -> str:
        return _json_result(
            session.run("bind_point_to_node", {"point_ref": point_ref, "node_id": node_id})
        )

    def locate_on_screenshot_vision(query: str, shot_ref: str | None = None) -> str:
        from backend.core.ai.vision_locate import locate_on_screenshot_vision as _vision

        return _json_result(
            _vision(session.artifacts, query=query, shot_ref=shot_ref, cfg=cfg)
        )

    def call_skill(skill_id: str, params: dict[str, Any] | None = None) -> str:
        """Optional macro: expand a skill pack into draft nodes."""
        from backend.core.ai.graphs.recipes import apply_flow_spec
        from backend.core.ai.lc.structured import FlowSpec, PlanStep

        spec = FlowSpec(
            steps=[
                PlanStep(
                    action="call_skill",
                    recipe=str(skill_id or "").strip(),
                    params=dict(params or {}),
                )
            ]
        )
        out = apply_flow_spec(
            session.draft,
            spec,
            artifacts=session.artifacts,
            allow_dangerous=session.runtime.allow_dangerous,
            strict_coords=session.runtime.strict_coords,
            tool_trace=session.tool_trace,
        )
        session.draft = out["draft"]
        session.artifacts = out["artifacts"]
        return _json_result(
            {
                "ok": out.get("ok"),
                "errors": out.get("errors"),
                "node_count": len((session.draft.get("nodes") or {})),
            }
        )

    return [
        StructuredTool.from_function(
            func=list_blocks,
            name="list_blocks",
            description="列出可用积木（不确定类型时再用；高频积木不必每轮都查）",
            args_schema=ListBlocksArgs,
        ),
        StructuredTool.from_function(
            func=get_block_schema,
            name="get_block_schema",
            description="读取单个积木的参数 schema",
            args_schema=GetBlockSchemaArgs,
        ),
        StructuredTool.from_function(
            func=draft_add_node,
            name="draft_add_node",
            description="向草稿添加节点；坐标必须用 point_ref 或变量绑定",
            args_schema=DraftAddNodeArgs,
        ),
        StructuredTool.from_function(
            func=draft_update_node,
            name="draft_update_node",
            description="更新草稿节点参数",
            args_schema=DraftUpdateNodeArgs,
        ),
        StructuredTool.from_function(
            func=draft_remove_node,
            name="draft_remove_node",
            description="删除草稿节点",
            args_schema=DraftRemoveNodeArgs,
        ),
        StructuredTool.from_function(
            func=draft_connect,
            name="draft_connect",
            description="连接两个节点",
            args_schema=DraftConnectArgs,
        ),
        StructuredTool.from_function(
            func=draft_set_entry,
            name="draft_set_entry",
            description="设置流程入口节点",
            args_schema=DraftSetEntryArgs,
        ),
        StructuredTool.from_function(
            func=draft_get,
            name="draft_get",
            description="查看当前草稿摘要",
        ),
        StructuredTool.from_function(
            func=capture_screen,
            name="capture_screen",
            description="截取当前屏幕到会话 artifacts",
            args_schema=CaptureScreenArgs,
        ),
        StructuredTool.from_function(
            func=locate_text_on_screen,
            name="locate_text_on_screen",
            description="在截图上 OCR 定位文字，返回 point_ref",
            args_schema=LocateTextArgs,
        ),
        StructuredTool.from_function(
            func=pack_point,
            name="pack_point",
            description="将已知坐标打包为 point_ref（仅用于用户确认过的点）",
            args_schema=PackPointArgs,
        ),
        StructuredTool.from_function(
            func=bind_point_to_node,
            name="bind_point_to_node",
            description="把 point_ref 绑定到节点坐标参数",
            args_schema=BindPointArgs,
        ),
        StructuredTool.from_function(
            func=locate_on_screenshot_vision,
            name="locate_on_screenshot_vision",
            description="多模态看截图定点，返回 point_ref（需先 capture_screen）",
            args_schema=VisionLocateArgs,
        ),
        StructuredTool.from_function(
            func=call_skill,
            name="call_skill",
            description="可选：调用技能宏展开节点（参数必须来自用户/澄清）",
            args_schema=CallSkillArgs,
        ),
    ]
