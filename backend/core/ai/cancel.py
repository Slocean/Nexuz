"""AI 轮次取消 + 通用超时执行工具。

取消模型：
- conversation_id → threading.Event 注册表；session_manager.chat() 每轮
  start_turn / finish_turn，api.ai_chat_stop（或前端停止按钮）触发 stop_turn。
- TurnCancelled 继承 BaseException：绕过链路上所有 `except Exception` 的
  通用兜底（与 asyncio.CancelledError 同思路），只在明确关心取消的边界
  （session_manager.chat / api worker）被捕获并优雅收尾。
- 检查点（checkpoint）埋在：flow 图每个节点入口（build_flow_graph 包装）、
  结构化工具循环每次迭代（flow_graph._run_structured_action_loop）、
  流式 token 循环（streaming.stream_chat_model，经 cancel_check 注入）。

超时模型：
- run_with_timeout 在短命守护线程中执行 fn，超时后弃置线程并返回
  (False, None)。被弃置的线程无法强杀，依赖积木自身超时/should_stop
  自行消亡（配合 run_block 的 wait 上限钳制）。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TurnCancelled(BaseException):
    """AI 轮次被用户取消。继承 BaseException 以绕过通用 except Exception。"""

    def __init__(self, message: str = "已按用户要求停止"):
        super().__init__(message)
        self.message = message


_events: dict[str, threading.Event] = {}
_lock = threading.Lock()


def start_turn(conversation_id: str) -> None:
    """注册一轮可取消的 AI 轮次（重复调用重置为未取消）。"""
    cid = str(conversation_id or "")
    if not cid:
        return
    with _lock:
        _events[cid] = threading.Event()


def finish_turn(conversation_id: str) -> None:
    """注销轮次（无论正常结束/失败/取消）。"""
    cid = str(conversation_id or "")
    with _lock:
        _events.pop(cid, None)


def is_cancelled(conversation_id: str) -> bool:
    cid = str(conversation_id or "")
    if not cid:
        return False
    with _lock:
        ev = _events.get(cid)
    return bool(ev is not None and ev.is_set())


def checkpoint(conversation_id: str) -> None:
    """取消点：已取消时抛 TurnCancelled。"""
    if is_cancelled(conversation_id):
        raise TurnCancelled()


def stop_turn(conversation_id: str) -> bool:
    """请求取消一轮进行中的 AI 轮次；返回是否存在该轮次。"""
    cid = str(conversation_id or "")
    with _lock:
        ev = _events.get(cid)
    if ev is None:
        return False
    ev.set()
    return True


def run_with_timeout(
    fn: Callable[[], T],
    *,
    timeout_s: float,
) -> tuple[bool, T | None]:
    """(finished, result)：fn 在守护线程执行；超时弃置并返回 (False, None)。

    fn 抛出的异常原样重抛（finished=True 时刻）。弃置的线程靠积木自身的
    超时 / should_stop 信号自行退出。
    """
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样转交主线程
            box["error"] = exc

    worker = threading.Thread(target=_target, daemon=True, name="nexuz-ai-timeout")
    worker.start()
    worker.join(max(0.05, float(timeout_s)))
    if worker.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("result")
