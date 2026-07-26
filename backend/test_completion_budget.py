"""Tests for model-aware completion budgets."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.lc.completion_budget import (
    is_local_base_url,
    is_reasoning_model,
    reasoning_extra_body,
    resolve_max_tokens,
)
from backend.core.ai.types import AiConfig


def test_is_reasoning_model_kimi():
    assert is_reasoning_model("kimi-k2.5")
    assert is_reasoning_model("moonshot-kimi-k2")
    assert not is_reasoning_model("gpt-4o-mini")
    assert not is_reasoning_model("google/gemma-4-26b")


def test_is_local_base_url():
    assert is_local_base_url("http://127.0.0.1:1234/v1")
    assert is_local_base_url("http://localhost:11434/v1")
    assert is_local_base_url("http://192.168.1.8:1234/v1")
    assert not is_local_base_url("https://api.moonshot.cn/v1")
    assert not is_local_base_url("https://api.openai.com/v1")


def test_resolve_max_tokens_tiers():
    local = AiConfig(
        base_url="http://127.0.0.1:1234/v1",
        model="google/gemma-4-26b",
        api_key="x",
    )
    cloud = AiConfig(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="x",
    )
    kimi = AiConfig(
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2.5",
        api_key="x",
    )
    assert resolve_max_tokens(local, "understand") == 512
    assert resolve_max_tokens(cloud, "understand") == 1024
    assert resolve_max_tokens(kimi, "understand") == 4096
    assert resolve_max_tokens(kimi, "plan_ir") == 4096
    assert resolve_max_tokens(kimi, "understand", retry=True) == 8192
    assert resolve_max_tokens(local, "understand", retry=True) == 1024


def test_reasoning_extra_body_kimi_only():
    body = reasoning_extra_body("kimi-k2.5")
    assert body is not None
    assert "thinking" in body
    assert reasoning_extra_body("gpt-4o-mini") is None
