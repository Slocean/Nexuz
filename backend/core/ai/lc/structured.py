"""Structured outputs for step-wise Agent orchestration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ClarifyQuestion(BaseModel):
    id: str = Field(default="q1", description="问题 id")
    prompt: str = Field(description="向用户展示的问题")
    choices: list[str] = Field(default_factory=list, description="可选项；空则自由填写")
    allow_free_text: bool = Field(default=True)


class IntentUnderstanding(BaseModel):
    """Phase 1: understand user intent (no Flow JSON)."""

    intent: str = Field(default="", description="一句话真实意图")
    known_slots: dict[str, str] = Field(
        default_factory=dict,
        description="已从话术抽出的槽位：contact/message/window_title/run_at/schedule 等",
    )
    ambiguities: list[ClarifyQuestion] = Field(
        default_factory=list,
        description="仅真歧义/缺参；禁止假确认题",
    )


class OutlineStep(BaseModel):
    """One high-level orchestration step (not a Flow node yet)."""

    id: str = Field(default="s1")
    goal: str = Field(description="这一步要达成什么")
    block_hint: str = Field(
        default="",
        description="建议积木：delay/type_text/key_press/window_activate/ocr_click/"
        "schedule_trigger/click/wait_until/find_image/…",
    )
    needs_sense: Literal["none", "ocr", "vision"] = Field(
        default="none",
        description="配参感知：文字点选用 ocr；无字图标用 vision；否则 none",
    )
    match_text: str | None = Field(default=None, description="OCR/点击匹配文字")
    params: dict[str, Any] = Field(default_factory=dict, description="已知关键参数")
    note: str = Field(default="")


class PlanOutline(BaseModel):
    """Phase 3: ordered approach before tool building."""

    summary: str = Field(default="")
    steps: list[OutlineStep] = Field(default_factory=list)


class GapCheckResult(BaseModel):
    complete: bool = Field(default=True)
    missing: list[str] = Field(
        default_factory=list,
        description="相对意图仍缺的步骤或槽位说明",
    )
    hints: list[str] = Field(
        default_factory=list,
        description="给下一轮 outline 的补洞提示",
    )


class ToolAction(BaseModel):
    """One tool invocation expressed as JSON (no native function-calling API)."""

    name: str = Field(
        description=(
            "工具名：draft_add_node / draft_connect / draft_set_entry / draft_update_node / "
            "draft_get / draft_remove_node / list_blocks / get_block_schema / "
            "capture_screen / locate_text_on_screen / locate_on_screenshot_vision / "
            "pack_point / bind_point_to_node / call_skill；完成则 done"
        )
    )
    args: dict[str, Any] = Field(default_factory=dict, description="工具参数")


class ToolActionBatch(BaseModel):
    """One ReAct round without OpenAI/LM Studio native tools / jinja templates."""

    actions: list[ToolAction] = Field(
        default_factory=list,
        description="本轮要执行的工具调用；全部完成时输出 [{name:done}]",
    )
    rationale: str = Field(default="", description="简短说明本轮意图")


# --- Legacy FlowSpec (kept for recipes / optional call_skill / eval heuristics) ---


class PlanStep(BaseModel):
    """One planned automation step (recipe / skill expansion)."""

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
        "call_skill",
    ] = Field(default="add")
    block_type: str | None = Field(default=None)
    node_id: str | None = Field(default=None)
    from_id: str | None = Field(default=None)
    to_id: str | None = Field(default=None)
    edge: str = Field(default="next")
    params: dict[str, Any] = Field(default_factory=dict)
    match_text: str | None = Field(default=None)
    recipe: str | None = Field(default=None)
    note: str | None = Field(default=None)


class FlowSpec(BaseModel):
    intent_summary: str = Field(default="")
    needs_locate: bool = Field(default=False)
    prefer_vision: bool = Field(default=False)
    steps: list[PlanStep] = Field(default_factory=list)
    locate_texts: list[str] = Field(default_factory=list)
    clarify_questions: list[ClarifyQuestion] = Field(default_factory=list)


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
