"""单一模型能力表：所有"按模型名子串匹配"的知识集中此处。

背景：固定 temperature 表、推理模型标记、preset 上下文窗口曾在
lc/models.py、token_scheduler/capability.py、providers/openai_compat.py
三处重复维护，已经漂移（kimi 的固定温度一处 0.6 一处 1.0）。
现在新增/修正模型只改本文件。

原则：
- 名字匹配是"弱提示"——用户显式配置（context_window_tokens 等）永远优先。
- 固定 temperature 规则来自实测（kimi-k2.5 只接受 0.6；OpenAI o 系/gpt-5/
  deepseek-r1 只接受 1.0）；不要假设所有"推理"模型都是 1.0。
"""

from __future__ import annotations

# 固定 temperature 规则：模型名（小写）包含任一 marker → 必须使用该 temperature。
# 顺序即优先级（先命中先得）。
FIXED_TEMPERATURE_RULES: tuple[tuple[tuple[str, ...], float], ...] = (
    (("kimi", "k2.5", "k2-", "k2."), 0.6),
    (("o1", "o3", "o4", "gpt-5", "reasoner", "deepseek-r1"), 1.0),
)

# 推理模型弱标记（用于预算/关闭 vendor thinking 的旋钮选择）。
# 绝不作为唯一预算权威——上下文窗口由 preset/显式配置决定。
REASONING_MARKERS: tuple[str, ...] = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "reasoner",
    "deepseek-r1",
    "deepseek-reasoner",
    "kimi",
    "k2.5",
    "k2-",
    "k2.",
    "qwq",
    "thinking",
)

# preset → 上下文窗口弱默认（token_scheduler 用；用户显式
# context_window_tokens 优先）。与各厂商 2026 现行产品对齐：
# dashscope(qwen-max/plus) 128k、moonshot(kimi) 128k。
PRESET_CONTEXT: dict[str, int] = {
    "openai": 128_000,
    "deepseek": 64_000,
    "dashscope": 128_000,
    "moonshot": 128_000,
    "zhipu": 128_000,
    "ollama": 8_192,
    "lmstudio": 8_192,
    "custom": 32_000,
}

DEFAULT_LOCAL_CONTEXT = 8_192
DEFAULT_CLOUD_CONTEXT = 32_768


def _name(model: str | None) -> str:
    return (model or "").strip().lower()


def fixed_temperature(model: str | None) -> float | None:
    """返回该模型必须使用的 temperature；无约束时 None。"""
    name = _name(model)
    if not name:
        return None
    for markers, temp in FIXED_TEMPERATURE_RULES:
        if any(m in name for m in markers):
            return float(temp)
    return None


def requires_temperature_one(model: str | None) -> bool:
    """向后兼容语义：仅当固定 temperature 恰为 1.0 时 True。"""
    return fixed_temperature(model) == 1.0


def is_reasoning_model(model: str | None) -> bool:
    """弱名字提示：命中推理标记时 True。"""
    name = _name(model)
    if not name:
        return False
    return any(m in name for m in REASONING_MARKERS)
