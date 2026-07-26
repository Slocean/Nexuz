"""Dual-budget Agent Token Scheduler tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.token_scheduler import (
    ContextLayer,
    compile_layers,
    estimate_tokens,
    is_incomplete_json_text,
    plan_call,
    plan_output_tokens,
    resolve_capability,
)
from backend.core.ai.token_scheduler.memory import episodic_from_messages
from backend.core.ai.types import AiConfig


def test_plan_call_output_first_reduces_input():
    cfg = AiConfig(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="x",
        context_window_tokens=8192,
    )
    b = plan_call(cfg, "understand", system_text="sys " * 50)
    assert b.reserved_output_tokens == plan_output_tokens(cfg, "understand")
    assert b.available_input == (
        b.max_context_tokens
        - b.reserved_output_tokens
        - b.safety_margin
        - b.system_tokens
        - b.tool_overhead_tokens
    )
    assert b.available_input >= 256
    assert b.max_tokens == b.reserved_output_tokens


def test_explicit_context_window_overrides_preset():
    local = AiConfig(
        base_url="http://127.0.0.1:1234/v1",
        model="anything",
        api_key="x",
        preset="lmstudio",
        context_window_tokens=16000,
    )
    caps = resolve_capability(local)
    assert caps.max_context_tokens == 16000


def test_compile_layers_drops_low_priority_first():
    layers = [
        ContextLayer("task", 0, "MUST_KEEP " * 20, compressible=False),
        ContextLayer("long", 3, "NOISE " * 400, compressible=True),
    ]
    packed = compile_layers(layers, budget_tokens=80)
    assert "MUST_KEEP" in packed
    assert estimate_tokens(packed) <= 90


def test_incomplete_json_guard():
    assert is_incomplete_json_text('{"a": 1')
    assert not is_incomplete_json_text('{"a": 1}')


def test_episodic_keyword_retrieval():
    msgs = [
        {"role": "user", "content": "打开微信给文件传输助手发你好"},
        {"role": "assistant", "content": "已准备草稿"},
        {"role": "user", "content": "天气怎么样"},
    ]
    hit = episodic_from_messages(msgs, query="微信 文件传输助手", budget_tokens=400)
    assert "微信" in hit or "文件传输助手" in hit


def test_kimi_output_profile_high():
    kimi = AiConfig(
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2.5",
        api_key="x",
        preset="moonshot",
    )
    assert plan_output_tokens(kimi, "understand") == 4096
    assert plan_call(kimi, "understand", retry=True).max_tokens == 8192
