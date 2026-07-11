"""Flow interpreter with pause / stop / step support."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

from .expression import evaluate_expression
from .registry import get_handler
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

    @property
    def running(self) -> bool:
        return self._running

    def run_flow(self, flow: dict[str, Any], step_mode: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise RuntimeError("已有流程正在执行")
            self._running = True
            self._stop_flag.clear()
            self._pause_event.set()
            self._step_mode = step_mode
            self._step_event.clear()

        def worker():
            try:
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
        self._pause_event.clear()
        self._emit("flow_paused", {})

    def resume(self) -> None:
        self._pause_event.set()
        self._emit("flow_resumed", {})

    def stop(self) -> None:
        self._stop_flag.set()
        self._pause_event.set()
        self._step_event.set()
        self._emit("flow_stopped", {})

    def step(self) -> None:
        self._step_mode = True
        self._step_event.set()
        self._pause_event.set()

    def wait_until_idle(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def _wait_controls(self) -> None:
        if self._stop_flag.is_set():
            raise InterruptedError("流程已停止")
        self._pause_event.wait()
        if self._stop_flag.is_set():
            raise InterruptedError("流程已停止")
        if self._step_mode:
            self._step_event.wait()
            self._step_event.clear()
            if self._stop_flag.is_set():
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
                {"node_id": node_id, "type": block_type, "params": params},
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
                    )
                    or {}
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                for out_name, val in result.items():
                    context[f"{node_id}.{out_name}"] = val
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "result": result,
                        "elapsed_ms": round(elapsed_ms, 2),
                        "ok": True,
                    },
                )
            except InterruptedError:
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

        if block_type in ("if_condition", "if_color_match", "if_text_contains"):
            matched = bool(result.get("matched"))
            nxt = node.get("then") if matched else node.get("else")
            return self._resolve_fallthrough(nxt, loop_stack), loop_stack

        if block_type == "switch":
            variable = (node.get("params") or {}).get("variable")
            current = resolve_value(variable, context) if variable else None
            for case in (node.get("params") or {}).get("cases") or []:
                if str(case.get("value")) == str(current):
                    return self._resolve_fallthrough(case.get("node_id"), loop_stack), loop_stack
            default = (
                (node.get("params") or {}).get("default")
                or node.get("default")
                or node.get("next")
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
                end = time.time() + interval / 1000.0
                while time.time() < end:
                    if self._stop_flag.is_set():
                        raise InterruptedError("流程已停止")
                    time.sleep(min(0.05, max(0, end - time.time())))
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
