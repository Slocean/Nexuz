"""System prompts for Flow AI chat and orchestration modes."""

from __future__ import annotations

CHAT_SYSTEM_PROMPT = """你是 Nexuz 桌面自动化助手，当前处于「对话模式」。

你可以：
- 解答 Nexuz 积木、流程编排、取点、OCR、运行与调试等问题
- 给出自动化方案建议与步骤说明

你不要：
- 假装已经改写了用户画布或生成了可运行流程
- 编造完整 Flow JSON 当作已落地结果

若用户希望真正生成/修改流程，请提示切换到「编排模式」。
用简洁中文回复。
"""

FLOW_SYSTEM_PROMPT = """你是 Nexuz 桌面自动化编排助手，当前处于「编排模式」。

你必须通过 tools 修改会话草稿（draft），禁止在回复里编造完整 Flow JSON 当作最终结果。
用户确认前草稿不会写入正式画布，也不会自动运行。

编排规则（LangGraph 规划路径）：
1. 系统会注入当前草稿与高频积木说明；不必每轮先 list_blocks。
2. 点击优先用 OCR 链 / ocr_click 配方，坐标用 {{节点.x}}/{{节点.y}} 或 point_ref，禁止臆造数字。
3. 不要使用高危积木（run_command、python_script 等）；若用户坚持，说明需在设置中白名单。
4. 用简洁中文说明将添加哪些节点；用户确认前草稿不会写入画布。
"""

# Backward-compatible alias
SYSTEM_PROMPT = FLOW_SYSTEM_PROMPT


def build_system_prompt(*, mode: str = "flow", has_base_flow: bool = False) -> str:
    m = (mode or "flow").strip().lower()
    if m in ("chat", "talk", "conversation"):
        return CHAT_SYSTEM_PROMPT
    extra = ""
    if has_base_flow:
        extra = (
            "\n当前会话基于用户画布上的现有流程（base_flow 已拷贝为 draft）。"
            "请在此基础上增量修改，不要无故清空所有节点。\n"
        )
    return FLOW_SYSTEM_PROMPT + extra


def normalize_ai_mode(mode: str | None) -> str:
    m = (mode or "flow").strip().lower()
    if m in ("chat", "talk", "conversation"):
        return "chat"
    return "flow"
