"""LLM 调用统一重试层：瞬态错误（429/5xx/超时/连接）指数退避。

设计：
- 只重试"瞬态"错误（is_transient_error）；参数/鉴权/模板错误立即抛出。
- 默认 retries=2（共 3 次尝试），base_delay=1.0s 指数退避 ± 抖动。
- with_retry 不感知 LLM 语义，纯函数级包装；调用点见
  lc/structured_call.py（结构化主链路）与 graphs/streaming.py（流式首包）。
- SDK 层（langchain ChatOpenAI.max_retries，lc/models.py）已有短退避重试；
  本层在其之上处理"重试耗尽后仍失败"的持续性抖动与网关重启窗口。
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# 默认重试次数（额外尝试次数，总尝试 = retries + 1）
DEFAULT_RETRIES = 2
DEFAULT_BASE_DELAY = 1.0

# 瞬态 HTTP 状态（httpx / openai SDK 异常的 status_code 或 response.status_code）
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# 错误文本标记（小写匹配）——本地网关文案差异大，宁可多匹配不可漏
_TRANSIENT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "too many requests",
    "timeout",
    "timed out",
    "timedout",
    "connection error",
    "connection reset",
    "connection refused",
    "connection aborted",
    "connect error",
    "failed to establish",
    "temporarily unavailable",
    "server is busy",
    "server overloaded",
    "overloaded",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway time-out",
    "try again",
)

# 明确非瞬态的文本（避免误重试，优先级高于上面的标记）
_NON_TRANSIENT_MARKERS = (
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "authentication",
    "401",
    "403",
    "permission",
    "invalid model",
    "model not found",
    "not found",
    "context length",
    "invalid request",
    "bad request",
)


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def is_transient_error(exc: BaseException) -> bool:
    """网络类瞬态错误判定：状态码优先，文本标记兜底。"""
    status = _status_code(exc)
    if status is not None:
        return status in _TRANSIENT_STATUS
    text = str(exc).lower()
    if any(m in text for m in _NON_TRANSIENT_MARKERS):
        return False
    return any(m in text for m in _TRANSIENT_MARKERS)


def retry_delay(attempt: int, *, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    """第 attempt 次失败后的等待秒数（attempt 从 0 起），指数 + 抖动。"""
    return base_delay * (2 ** max(0, attempt)) + random.uniform(0.0, 0.5)


def with_retry(
    fn: Callable[[], T],
    *,
    retries: int = DEFAULT_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    what: str = "",
    on_retry: Callable[[BaseException, int, float], None] | None = None,
) -> T:
    """执行 fn()，瞬态错误指数退避重试；非瞬态错误或重试耗尽时抛出最后异常。

    on_retry(exc, attempt, delay) 仅供日志/进度回调，异常会被吞掉。
    """
    last_exc: BaseException | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 调用方决定如何处理最终异常
            last_exc = exc
            if attempt >= retries or not is_transient_error(exc):
                raise
            delay = retry_delay(attempt, base_delay=base_delay)
            if on_retry is not None:
                try:
                    on_retry(exc, attempt + 1, delay)
                except Exception:
                    pass
            time.sleep(delay)
    raise last_exc  # pragma: no cover - 循环必经 return/raise
