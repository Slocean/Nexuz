"""retry：瞬态错误判定 + with_retry 指数退避行为。"""

from __future__ import annotations

import pytest

from backend.core.ai import retry
from backend.core.ai.retry import is_transient_error, retry_delay, with_retry


class _HttpLike(Exception):
    """带 status_code 的异常形状（httpx / openai SDK 风格）。"""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def test_transient_by_status_code():
    assert is_transient_error(_HttpLike(429)) is True
    assert is_transient_error(_HttpLike(503)) is True
    assert is_transient_error(_HttpLike(400)) is False
    assert is_transient_error(_HttpLike(401)) is False


def test_transient_by_text_markers():
    assert is_transient_error(Exception("Connection reset by peer")) is True
    assert is_transient_error(Exception("Request timed out after 30s")) is True
    assert is_transient_error(Exception("Server overloaded, try again")) is True


def test_non_transient_text():
    assert is_transient_error(Exception("Invalid API key provided")) is False
    assert is_transient_error(Exception("model not found: gpt-x")) is False
    assert is_transient_error(Exception("context length exceeded")) is False
    assert is_transient_error(ValueError("bad params")) is False


def test_non_transient_marker_beats_transient_marker():
    # 文本同时含两类标记时，明确非瞬态优先
    assert is_transient_error(Exception("401 unauthorized: too many requests")) is False


def test_retry_delay_exponential():
    d0 = retry_delay(0, base_delay=1.0)
    d3 = retry_delay(3, base_delay=1.0)
    assert 1.0 <= d0 <= 1.5
    assert 8.0 <= d3 <= 8.5


def test_with_retry_succeeds_after_transient(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _HttpLike(503)
        return "ok"

    assert with_retry(flaky) == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_non_transient_immediately(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise ValueError("invalid api key")

    with pytest.raises(ValueError):
        with_retry(bad, retries=3)
    assert calls["n"] == 1


def test_with_retry_exhausts_and_raises_last(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    retried = []

    def always_down():
        calls["n"] += 1
        raise _HttpLike(502)

    with pytest.raises(_HttpLike):
        with_retry(always_down, retries=2, on_retry=lambda exc, a, d: retried.append(a))
    assert calls["n"] == 3  # 首次 + 2 次重试
    assert retried == [1, 2]
