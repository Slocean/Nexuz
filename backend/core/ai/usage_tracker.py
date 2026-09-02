"""按轮次累计 LLM token usage（thread-local）。

数据流：
- session_manager.chat() 每轮开始 start_turn()、结束 finish_turn()；
- LLM 调用点通过两种方式上报：
  1) invoke 路径：Runnable config 里挂 UsageCallback（on_llm_end 提取
     LLMResult 的 token_usage / usage_metadata）——见 lc/structured_call.py；
  2) 流式路径：从带 usage_metadata 的 chunk / 兜底 invoke 的 AIMessage 提取
     ——见 graphs/streaming.py。
- 不在轮次内（如设置页"测试连接"）时 record() 直接丢弃、callbacks() 返回空。

汇总结构：{"calls", "input_tokens", "output_tokens", "total_tokens",
"no_usage"}（no_usage = 网关未回传 token 数的调用次数）。
"""

from __future__ import annotations

import threading
from typing import Any

_local = threading.local()

_KEYS = ("input_tokens", "output_tokens", "total_tokens")


def _new_acc() -> dict[str, int]:
    return {"calls": 0, "no_usage": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _stack() -> list[dict[str, int]]:
    st = getattr(_local, "stack", None)
    if st is None:
        st = []
        _local.stack = st
    return st


def start_turn() -> None:
    """开始一轮 AI 会话：压入新的累计器（支持嵌套，按最内层统计）。"""
    _stack().append(_new_acc())


def snapshot() -> dict[str, int]:
    """当前轮次累计值（不结束轮次），供轮次中途写审计使用。"""
    st = _stack()
    return dict(st[-1]) if st else _new_acc()


def finish_turn() -> dict[str, int]:
    """结束当前轮次并返回累计值；无进行中轮次时返回全零。"""
    st = _stack()
    return dict(st.pop()) if st else _new_acc()


def record(usage: dict[str, Any] | None) -> None:
    """累加一次调用；usage=None / 字段缺失按"无 token 信息"计数（no_usage）。

    轮次外安全忽略（如设置页连接测试）。
    """
    st = _stack()
    if not st:
        return
    acc = st[-1]
    got_any = False
    if isinstance(usage, dict):
        for key in _KEYS:
            val = usage.get(key)
            if isinstance(val, (int, float)) and val >= 0:
                acc[key] += int(val)
                got_any = True
    acc["calls"] += 1
    if not got_any:
        acc["no_usage"] += 1


# ---------------------------------------------------------------------------
# 从 LangChain 响应形状提取 usage
# ---------------------------------------------------------------------------


def extract_message_usage(msg: Any) -> dict[str, Any] | None:
    """AIMessage → usage dict；无 token 信息时返回 None。"""
    um = getattr(msg, "usage_metadata", None)
    if isinstance(um, dict) and (um.get("input_tokens") or um.get("output_tokens")):
        return {
            "input_tokens": um.get("input_tokens"),
            "output_tokens": um.get("output_tokens"),
            "total_tokens": um.get("total_tokens"),
        }
    rm = getattr(msg, "response_metadata", None)
    tu = rm.get("token_usage") if isinstance(rm, dict) else None
    if isinstance(tu, dict) and (tu.get("prompt_tokens") or tu.get("completion_tokens")):
        return {
            "input_tokens": tu.get("prompt_tokens"),
            "output_tokens": tu.get("completion_tokens"),
            "total_tokens": tu.get("total_tokens"),
        }
    return None


def record_message(msg: Any) -> None:
    record(extract_message_usage(msg))


def _record_llm_result(response: Any) -> None:
    # 优先 llm_output.token_usage（整个请求级），否则取 generation 内消息
    llm_output = getattr(response, "llm_output", None)
    tu = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
    if isinstance(tu, dict) and (tu.get("prompt_tokens") or tu.get("completion_tokens")):
        record(
            {
                "input_tokens": tu.get("prompt_tokens"),
                "output_tokens": tu.get("completion_tokens"),
                "total_tokens": tu.get("total_tokens"),
            }
        )
        return
    for gens in getattr(response, "generations", None) or []:
        for gen in gens or []:
            usage = extract_message_usage(getattr(gen, "message", None))
            if usage is not None:
                record(usage)
                return
    record(None)


try:  # langchain_core 缺失时退化为普通类（仅影响 on_llm_end 分发，不影响模块导入）
    from langchain_core.callbacks import BaseCallbackHandler as _BaseHandler
except Exception:  # pragma: no cover

    class _BaseHandler:  # type: ignore[no-redef]
        pass


class UsageCallback(_BaseHandler):
    """Runnable config 回调：捕获每次模型调用的 usage（on_llm_end）。"""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            _record_llm_result(response)
        except Exception:
            pass


def callbacks() -> list[Any]:
    """进行中的轮次返回 [UsageCallback]，否则空列表。"""
    if not _stack():
        return []
    return [UsageCallback()]


def runnable_config() -> dict[str, Any] | None:
    """Runnable.invoke(..., config=...) 用；轮次外返回 None（零开销）。"""
    cbs = callbacks()
    return {"callbacks": cbs} if cbs else None
