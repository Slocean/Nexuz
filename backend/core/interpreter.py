"""Flow interpreter with pause / stop / step support."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

from .expression import evaluate_expression
from .registry import get_handler
from .runtime_payload import compact_context_value, summarize_params, summarize_result
from .variable_resolver import resolve_value, resolve_variables


class FlowInterpreter:
    def __init__(self, emit: Callable[[str, dict], None] | None = None):
        self._emit = emit or (lambda _event, _payload: None)
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_flag = threading.Event()
        self._step_mode = False
        self._step_event = threading.Event()
        self._running = False
        self._lock = threading.Lock()
        # Optional parent controls when nested (call_subflow).
        self._parent_should_stop: Callable[[], bool] | None = None
        self._parent_cooperate: Callable[[], None] | None = None

    def bind_parent_controls(
        self,
        should_stop: Callable[[], bool] | None = None,
        cooperate: Callable[[], None] | None = None,
    ) -> None:
        """Wire nested interpreter to parent pause/stop (call_subflow)."""
        self._parent_should_stop = should_stop
        self._parent_cooperate = cooperate

    def _is_stop_requested(self) -> bool:
        if self._stop_flag.is_set():
            return True
        if self._parent_should_stop is not None and self._parent_should_stop():
            return True
        return False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._running and not self._pause_event.is_set()

    def run_flow(self, flow: dict[str, Any], step_mode: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._running:
                # Paused session: treat as resume instead of starting a second run.
                if not self._pause_event.is_set() and not self._stop_flag.is_set():
                    self._pause_event.set()
                    self._step_mode = bool(step_mode)
                    if step_mode:
                        self._step_event.set()
                    self._emit("flow_resumed", {"via": "run"})
                    return {"started": False, "resumed": True}
                raise RuntimeError("已有流程正在执行，请先停止或继续")
            self._running = True
            self._stop_flag.clear()
            self._pause_event.set()
            self._step_mode = step_mode
            self._step_event.clear()

        def worker():
            try:
                try:
                    from backend.core.input.frida.session_manager import get_frida_session_manager

                    get_frida_session_manager().clear_resolve_cache()
                except Exception:
                    pass
                self._execute(flow)
                self._emit("flow_finished", {"ok": True})
            except InterruptedError:
                self._emit("flow_finished", {"ok": False, "error": "已停止", "stopped": True})
            except Exception as exc:
                self._emit(
                    "flow_finished",
                    {"ok": False, "error": str(exc), "traceback": traceback.format_exc()},
                )
            finally:
                with self._lock:
                    self._running = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return {"started": True}

    def pause(self) -> None:
        if not self._running:
            return
        self._pause_event.clear()
        self._emit("flow_paused", {})

    def resume(self) -> None:
        if not self._running:
            return
        self._pause_event.set()
        self._emit("flow_resumed", {})

    def stop(self) -> None:
        if not self._running and not self._thread:
            self._emit("flow_finished", {"ok": False, "error": "当前没有运行中的流程", "stopped": True})
            return
        self._stop_flag.set()
        self._pause_event.set()
        self._step_event.set()
        # UI enters "stopping"; idle only after worker emits flow_finished.
        self._emit("flow_stopping", {})

    def step(self) -> None:
        self._step_mode = True
        self._step_event.set()
        self._pause_event.set()

    def wait_until_idle(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def _wait_controls(self) -> None:
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")
        if self._parent_cooperate is not None:
            self._parent_cooperate()
        else:
            self._pause_event.wait()
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")
        if self._step_mode:
            self._step_event.wait()
            self._step_event.clear()
            if self._is_stop_requested():
                raise InterruptedError("流程已停止")

    def _cooperate_wait(self) -> None:
        """Honor pause/stop inside a long-running block (delay, wait, etc.).

        Unlike ``_wait_controls``, this does not consume step tokens — step still
        advances per node, not per sleep chunk.
        """
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")
        if self._parent_cooperate is not None:
            self._parent_cooperate()
            if self._is_stop_requested():
                raise InterruptedError("流程已停止")
            return
        # stop() sets pause_event so a paused wait wakes and then sees stop.
        while not self._pause_event.wait(timeout=0.05):
            if self._is_stop_requested():
                raise InterruptedError("流程已停止")
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")

    def _execute(self, flow: dict[str, Any]) -> dict[str, Any]:
        nodes = flow.get("nodes") or {}
        entry = flow.get("entry")
        if not entry or entry not in nodes:
            raise ValueError("流程缺少有效 entry 节点")

        context: dict[str, Any] = {}
        for k, v in (flow.get("variables") or {}).items():
            context[k if str(k).startswith("$") else f"${k}"] = v
            context[str(k).lstrip("$")] = v
        if flow.get("__file_path__"):
            context["__flow_file_path__"] = flow["__file_path__"]

        loop_stack: list[str] = []
        node_id: str | None = entry

        while node_id:
            self._wait_controls()
            node = nodes.get(node_id)
            if not node:
                raise ValueError(f"节点不存在: {node_id}")

            block_type = node.get("type")
            handler = get_handler(block_type)
            if handler is None:
                raise ValueError(f"未知 Block 类型: {block_type}")

            params = resolve_variables(node.get("params") or {}, context)
            self._emit(
                "node_start",
                {
                    "node_id": node_id,
                    "type": block_type,
                    # Slim IPC payload — full params stay local for the handler only.
                    "params": summarize_params(params),
                },
            )
            t0 = time.perf_counter()
            try:
                result = (
                    handler(
                        params,
                        context,
                        node=node,
                        node_id=node_id,
                        flow=flow,
                        emit=self._emit,
                        should_stop=self._is_stop_requested,
                        cooperate=self._cooperate_wait,
                    )
                    or {}
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                for out_name, val in result.items():
                    ctx_key = f"{node_id}.{out_name}"
                    context[ctx_key] = compact_context_value(ctx_key, val)
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "result": summarize_result(result),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "ok": True,
                    },
                )
            except InterruptedError:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "error": "已停止",
                        "elapsed_ms": round(elapsed_ms, 2),
                        "ok": False,
                        "stopped": True,
                    },
                )
                raise
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "error": str(exc),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "ok": False,
                    },
                )
                raise

            nxt, loop_stack = self.decide_next(
                node, node_id, result, context, nodes, loop_stack
            )
            node_id = nxt

        return context

    def decide_next(
        self,
        node: dict[str, Any],
        node_id: str,
        result: dict[str, Any],
        context: dict[str, Any],
        nodes: dict[str, Any],
        loop_stack: list[str],
    ) -> tuple[str | None, list[str]]:
        block_type = node.get("type")

        if block_type in ("if_condition", "if_color_match", "if_text_contains", "if_logic"):
            matched = bool(result.get("matched"))
            nxt = node.get("then") if matched else node.get("else")
            return self._resolve_fallthrough(nxt, loop_stack), loop_stack

        if block_type == "switch":
            params = node.get("params") or {}
            variable = params.get("variable")
            current = resolve_value(variable, context) if variable else None
            # Missing refs resolve to ""; treat None the same for matching.
            current_s = "" if current is None else str(current)

            matched_target: str | None = None
            for case in params.get("cases") or []:
                if not isinstance(case, dict):
                    continue
                raw = case.get("value")
                # Empty match value never wins — those fall through to default.
                if raw is None or str(raw).strip() == "":
                    continue
                if str(raw) != current_s:
                    continue
                target = str(case.get("node_id") or "").strip()
                if target:
                    matched_target = target
                break

            if matched_target:
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "message": f"多分支匹配 → {matched_target}（值={current_s!r}）",
                        "node_id": node_id,
                    },
                )
                return self._resolve_fallthrough(matched_target, loop_stack), loop_stack

            default = (
                params.get("default")
                or node.get("default")
                or node.get("next")
                or ""
            )
            default = str(default).strip() or None
            self._emit(
                "log",
                {
                    "level": "info",
                    "message": (
                        f"多分支默认 → {default}（值={current_s!r}）"
                        if default
                        else f"多分支无默认目标（值={current_s!r}），流程结束"
                    ),
                    "node_id": node_id,
                },
            )
            return self._resolve_fallthrough(default, loop_stack), loop_stack

        if block_type == "loop_n":
            times = int((node.get("params") or {}).get("times") or 0)
            counter_key = f"__loop_{node_id}__counter"
            count = int(context.get(counter_key, 0))
            if count < times:
                context[counter_key] = count + 1
                body = node.get("body")
                if not body:
                    raise ValueError(f"loop_n 节点 {node_id} 缺少 body")
                if not loop_stack or loop_stack[-1] != node_id:
                    loop_stack = loop_stack + [node_id]
                return body, loop_stack
            context[counter_key] = 0
            if loop_stack and loop_stack[-1] == node_id:
                loop_stack = loop_stack[:-1]
            return self._resolve_fallthrough(node.get("next"), loop_stack), loop_stack

        if block_type == "loop_foreach":
            from backend.blocks.loop_foreach import _as_list, inject_item_var, _normalize_item_var

            params = node.get("params") or {}
            # Params may still be raw refs here — resolve against live context.
            collection = resolve_value(params.get("collection"), context)
            items = _as_list(collection)
            counter_key = f"__loop_{node_id}__counter"
            count = int(context.get(counter_key, 0))
            if count < len(items):
                item = items[count]
                context[counter_key] = count + 1
                inject_item_var(context, _normalize_item_var(params.get("item_var")), item)
                body = node.get("body")
                if not body:
                    raise ValueError(f"loop_foreach 节点 {node_id} 缺少 body")
                if not loop_stack or loop_stack[-1] != node_id:
                    loop_stack = loop_stack + [node_id]
                return body, loop_stack
            context[counter_key] = 0
            if loop_stack and loop_stack[-1] == node_id:
                loop_stack = loop_stack[:-1]
            return self._resolve_fallthrough(node.get("next"), loop_stack), loop_stack

        if block_type == "loop_while":
            params = node.get("params") or {}
            max_times = int(params.get("max_times") or 10000)
            counter_key = f"__loop_{node_id}__counter"
            count = int(context.get(counter_key, 0))
            should = evaluate_expression(str(params.get("expression") or ""), context)
            if should and count < max_times:
                context[counter_key] = count + 1
                body = node.get("body")
                if not body:
                    raise ValueError(f"loop_while 节点 {node_id} 缺少 body")
                if not loop_stack or loop_stack[-1] != node_id:
                    loop_stack = loop_stack + [node_id]
                return body, loop_stack
            context[counter_key] = 0
            if loop_stack and loop_stack[-1] == node_id:
                loop_stack = loop_stack[:-1]
            return self._resolve_fallthrough(node.get("next"), loop_stack), loop_stack

        if block_type == "loop_forever":
            params = node.get("params") or {}
            counter_key = f"__loop_{node_id}__counter"
            count = int(context.get(counter_key, 0))
            max_times = int(params.get("max_times") or 1_000_000)
            exit_cond = params.get("exit_condition")
            interval = int(params.get("check_interval_ms") or 0)
            if exit_cond and evaluate_expression(str(exit_cond), context):
                context[counter_key] = 0
                if loop_stack and loop_stack[-1] == node_id:
                    loop_stack = loop_stack[:-1]
                return self._resolve_fallthrough(node.get("next"), loop_stack), loop_stack
            if count >= max_times:
                context[counter_key] = 0
                if loop_stack and loop_stack[-1] == node_id:
                    loop_stack = loop_stack[:-1]
                return self._resolve_fallthrough(node.get("next"), loop_stack), loop_stack
            context[counter_key] = count + 1
            if interval > 0:
                from backend.blocks._helpers import interruptible_sleep

                interruptible_sleep(
                    interval / 1000.0,
                    should_stop=self._is_stop_requested,
                    cooperate=self._cooperate_wait,
                )
            body = node.get("body")
            if not body:
                raise ValueError(f"loop_forever 节点 {node_id} 缺少 body")
            if not loop_stack or loop_stack[-1] != node_id:
                loop_stack = loop_stack + [node_id]
            return body, loop_stack

        nxt = node.get("next")
        if nxt:
            return nxt, loop_stack
        # end of body → return to enclosing loop
        if loop_stack:
            return loop_stack[-1], loop_stack
        return None, loop_stack

    @staticmethod
    def _resolve_fallthrough(nxt: str | None, loop_stack: list[str]) -> str | None:
        if nxt:
            return nxt
        if loop_stack:
            return loop_stack[-1]
        return None


_interpreter: FlowInterpreter | None = None


def get_interpreter(emit: Callable[[str, dict], None] | None = None) -> FlowInterpreter:
    global _interpreter
    if _interpreter is None:
        _interpreter = FlowInterpreter(emit=emit)
    elif emit is not None:
        _interpreter._emit = emit
    return _interpreter
