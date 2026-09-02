"""阶段4：单一模型能力表 + 降级开关 TTL 复位。"""

from __future__ import annotations

import pytest

from backend.core.ai import model_capabilities as mc


# --- 单一能力表 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("kimi-k2.5", 0.6),
        ("Kimi-K2-Instruct", 0.6),
        ("moonshot-v1-k2.5", 0.6),
        ("o1", 1.0),
        ("o3-mini", 1.0),
        ("gpt-5", 1.0),
        ("deepseek-r1", 1.0),
        ("deepseek-reasoner", 1.0),  # "reasoner" 子串命中
        ("gpt-4o-mini", None),
        ("qwen-max", None),
        ("", None),
        (None, None),
    ],
)
def test_fixed_temperature_single_source(model, expected):
    assert mc.fixed_temperature(model) == expected


def test_requires_temperature_one_semantics():
    # 仅当固定温度恰为 1.0 时 True —— kimi(0.6) 不是
    assert mc.requires_temperature_one("o3") is True
    assert mc.requires_temperature_one("kimi-k2.5") is False
    assert mc.requires_temperature_one("gpt-4o") is False


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("qwq-32b", True),
        ("deepseek-reasoner", True),
        ("kimi-k2.5", True),
        ("gpt-4o-mini", False),
        ("", False),
    ],
)
def test_is_reasoning_model(model, expected):
    assert mc.is_reasoning_model(model) is expected


def test_legacy_consumers_delegate_to_single_source():
    """三个历史消费点必须与单一来源一致（防再次漂移）。"""
    from backend.core.ai.lc.models import resolve_fixed_temperature
    from backend.core.ai.providers.openai_compat import (
        _model_requires_temperature_one as oc_requires_one,
    )
    from backend.core.ai.token_scheduler.capability import is_reasoning_model

    for m in ("kimi-k2.5", "o3", "deepseek-r1", "gpt-4o"):
        assert resolve_fixed_temperature(m) == mc.fixed_temperature(m)
        assert oc_requires_one(m) == mc.requires_temperature_one(m)
        assert is_reasoning_model(m) == mc.is_reasoning_model(m)


def test_preset_context_updated():
    """dashscope/moonshot 与现行产品对齐（128k），不再是过时的 32k。"""
    assert mc.PRESET_CONTEXT["dashscope"] == 128_000
    assert mc.PRESET_CONTEXT["moonshot"] == 128_000


def test_capability_uses_preset_and_explicit_override():
    from backend.core.ai.token_scheduler.capability import resolve_capability
    from backend.core.ai.types import AiConfig

    cfg = AiConfig(base_url="https://api.x.com/v1", preset="dashscope", model="qwen-max")
    assert resolve_capability(cfg).max_context_tokens == 128_000

    # 显式配置永远优先于 preset 弱默认
    cfg2 = AiConfig(
        base_url="https://api.x.com/v1",
        preset="dashscope",
        model="qwen-max",
        context_window_tokens=32768,
    )
    assert resolve_capability(cfg2).max_context_tokens == 32768


# --- 降级开关 TTL 复位 -------------------------------------------------------


def test_json_mode_flag_ttl_reprobe(monkeypatch):
    """json_mode 降级：置位后生效，TTL 过期自动复位重探。"""
    from backend.core.ai.lc import structured_call as sc

    sc.reset_structured_call_guards()
    try:
        assert sc._json_mode_unsupported() is False
        sc._mark_json_mode_unsupported()
        assert sc._json_mode_unsupported() is True

        real_monotonic = sc.time.monotonic
        monkeypatch.setattr(
            sc.time, "monotonic", lambda: real_monotonic() + sc._JSON_MODE_REPROBE_S + 1
        )
        assert sc._json_mode_unsupported() is False  # TTL 过期 → 允许重探
    finally:
        sc.reset_structured_call_guards()


def test_native_tools_flag_ttl_reprobe(monkeypatch):
    """原生 bind_tools 降级：置位后生效，TTL 过期自动复位重探。"""
    from backend.core.ai.graphs import flow_graph as fg

    fg._NATIVE_TOOLS_UNAVAILABLE = False
    fg._NATIVE_TOOLS_UNAVAILABLE_AT = 0.0
    try:
        assert fg._native_tools_unavailable() is False
        fg._mark_native_tools_unavailable()
        assert fg._native_tools_unavailable() is True

        real_monotonic = fg.time.monotonic
        monkeypatch.setattr(
            fg.time, "monotonic", lambda: real_monotonic() + fg._NATIVE_TOOLS_REPROBE_S + 1
        )
        assert fg._native_tools_unavailable() is False
    finally:
        fg._NATIVE_TOOLS_UNAVAILABLE = False
        fg._NATIVE_TOOLS_UNAVAILABLE_AT = 0.0


def test_json_mode_cascade_skips_then_reprobes(monkeypatch):
    """级联行为：json_mode 被标记不支持后跳过；TTL 过期后重新尝试。"""
    from backend.core.ai.lc import structured_call as sc

    sc.reset_structured_call_guards()
    try:
        attempts: list[str] = []

        class _Bound:
            def __init__(self, method):
                self.method = method

            def invoke(self, messages, config=None):
                attempts.append(self.method or "default")
                if self.method == "json_schema":
                    raise Exception("could not parse response as json")  # 未知错误 → 换 method
                if self.method == "json_mode":
                    raise Exception("response_format.type must be 'json_schema' or 'text'")
                return {"ok": True}

        class _LLM:
            def with_structured_output(self, schema, method=None):
                return _Bound(method)

        r1 = sc.invoke_structured(_LLM(), dict, [("user", "hi")])
        assert r1 == {"ok": True}
        assert attempts == ["json_schema", "json_mode", "default"]

        # json_mode 已标记不支持 → 下次直接跳过
        attempts.clear()
        sc.invoke_structured(_LLM(), dict, [("user", "hi")])
        assert attempts == ["json_schema", "default"]

        # TTL 过期 → 重新尝试 json_mode（网关可能已修好）
        real_monotonic = sc.time.monotonic
        monkeypatch.setattr(
            sc.time, "monotonic", lambda: real_monotonic() + sc._JSON_MODE_REPROBE_S + 1
        )
        attempts.clear()
        sc.invoke_structured(_LLM(), dict, [("user", "hi")])
        assert "json_mode" in attempts
    finally:
        sc.reset_structured_call_guards()
