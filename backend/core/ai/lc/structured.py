"""Structured FlowSpec for planner / repair (LangChain with_structured_output)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """One planned automation step (not a raw Flow JSON node)."""

    action: Literal[
        "add",
        "update",
        "remove",
        "connect",
        "set_entry",
        "ocr_click",
        "type_text",
        "delay",
        "key_press",
        "recipe",
    ] = Field(
        default="add",
        description="步骤动作：add 加节点；ocr_click/type_text/delay 等为快捷意图；recipe 使用命名配方",
    )
    block_type: str | None = Field(
        default=None,
        description="积木类型，如 delay / type_text / click；recipe/ocr_click 时可空",
    )
    node_id: str | None = Field(default=None, description="指定节点 id（更新/删除/连线时）")
    from_id: str | None = Field(default=None, description="连线起点")
    to_id: str | None = Field(default=None, description="连线终点")
    edge: str = Field(default="next", description="边类型 next/then/else/body/catch/finally")
    params: dict[str, Any] = Field(default_factory=dict, description="关键参数意图")
    match_text: str | None = Field(default=None, description="OCR 点击要匹配的文字")
    recipe: str | None = Field(
        default=None,
        description="配方名：ocr_click_chain / delay_type / type_enter",
    )
    note: str | None = Field(default=None, description="给人看的简短说明")


class FlowSpec(BaseModel):
    """Planner output: ordered steps to build or patch a draft."""

    intent_summary: str = Field(default="", description="一句话概括用户意图")
    needs_locate: bool = Field(
        default=False,
        description="是否需要截图/OCR 取点（屏幕文字点击等）",
    )
    steps: list[PlanStep] = Field(default_factory=list, description="有序步骤")
    locate_texts: list[str] = Field(
        default_factory=list,
        description="需要在屏幕上定位的文字列表",
    )


def flow_spec_to_dict(spec: FlowSpec | dict[str, Any] | None) -> dict[str, Any]:
    if spec is None:
        return FlowSpec().model_dump()
    if isinstance(spec, FlowSpec):
        return spec.model_dump()
    if isinstance(spec, dict):
        return FlowSpec.model_validate(spec).model_dump()
    return FlowSpec().model_dump()


def parse_flow_spec(data: Any) -> FlowSpec:
    if isinstance(data, FlowSpec):
        return data
    if isinstance(data, dict):
        return FlowSpec.model_validate(data)
    return FlowSpec()
