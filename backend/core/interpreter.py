"""Flow interpreter with pause / stop / debug breakpoints / step."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable


from .expression import evaluate_expression
from .registry import get_handler
from .runtime_payload import (
    compact_context_value,
    summarize_node_outcome,
    summarize_params,
    summarize_result,
)
from .variable_resolver import resolve_value, resolve_variables


def node_pre_delay_ms(index: int, item_delay: Any, default_interval: Any = 0) -> int:
    """Resolve the wait before a node: explicit override wins, first global wait is skipped."""
    value = item_delay
    if value is None or value == "":
        if int(index) <= 0:
            return 0
        value = default_interval
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


class FlowInterpreter:
    def __init__(self, emit: Callable[[str, dict], None] | None = None):
        self._emit = emit or (lambda _event, _payload: None)
        self._thread: threading.Thread | None = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_flag = threading.Event()
        self._step_event = threading.Event()
        self._running = False
        self._run_id = 0  # generation token so old workers can't clobber a new run
        self._lock = threading.Lock()
        # Debug: honor breakpoints / step-over
        self._debug_mode = False
        self._breakpoints: set[str] = set()
        self._break_next = False  # stop before the next node (step / step-into start)
        self._at_breakpoint = False
        self._paused_node_id: str | None = None
        self._current_node_id: str | None = None
        self._flow_name: str = ""
        self._debug_context: dict[str, Any] = {}
        # Optional parent controls when nested (call_subflow).
        self._parent_should_stop: Callable[[], bool] | None = None
        self._parent_cooperate: Callable[[], None] | None = None

    def _thread_alive(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

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
        if not self._running:
            return False
        t = self._thread
        # Between assigning _running and start(), thread may briefly be None.
        if t is None:
            return True
        return t.is_alive()

    @property
    def paused(self) -> bool:
        return self.running and (not self._pause_event.is_set() or self._at_breakpoint)

    @property
    def at_breakpoint(self) -> bool:
        return self._at_breakpoint

    @property
    def debug_mode(self) -> bool:
        return self._debug_mode

    @property
    def current_node_id(self) -> str | None:
        with self._lock:
            return self._current_node_id

    @property
    def flow_name(self) -> str:
        with self._lock:
            return self._flow_name

    def set_breakpoints(self, node_ids: list[str] | None) -> None:
        with self._lock:
            self._breakpoints = {str(x) for x in (node_ids or []) if str(x).strip()}

    def run_flow(
        self,
        flow: dict[str, Any],
        step_mode: bool = False,
        debug_mode: bool = False,
        breakpoints: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._running and self._thread_alive():
                # Paused / breakpoint: treat as continue instead of starting a second run.
                if self.paused and not self._stop_flag.is_set():
                    self._break_next = bool(step_mode)
                    self._step_event.set()
                    self._pause_event.set()
                    self._emit("flow_resumed", {"via": "run"})
                    return {"started": False, "resumed": True}
                raise RuntimeError("已有流程正在执行，请先停止或继续")
            prev = self._thread

        # Ensure a previous worker fully exits before we clear flags / start again.
        if prev is not None and prev.is_alive():
            self._stop_flag.set()
            self._pause_event.set()
            self._step_event.set()
            prev.join(timeout=3.0)

        with self._lock:
            if self._running and self._thread_alive():
                raise RuntimeError("已有流程正在执行，请先停止或继续")
            self._run_id += 1
            run_id = self._run_id
            self._running = True
            self._stop_flag.clear()
            self._pause_event.set()
            self._step_event.clear()
            self._at_breakpoint = False
            self._paused_node_id = None
            self._current_node_id = None
            self._flow_name = str(flow.get("name") or flow.get("flow_id") or "").strip()
            # step_mode alone implies debug (legacy「单步」)
            self._debug_mode = bool(debug_mode) or bool(step_mode)
            bps = breakpoints
            if bps is None:
                bps = flow.get("breakpoints")
            self._breakpoints = {str(x) for x in (bps or []) if str(x).strip()}
            # Break before the first node when starting via「单步」
            self._break_next = bool(step_mode)

        if self._debug_mode:
            self._emit(
                "flow_debug",
                {
                    "breakpoints": sorted(self._breakpoints),
                    "step_first": bool(step_mode),
                },
            )

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
                    # Only the active generation may reset shared state.
                    if self._run_id == run_id:
                        self._running = False
                        self._at_breakpoint = False
                        self._paused_node_id = None
                        self._current_node_id = None
                        self._flow_name = ""
                        self._debug_mode = False
                        self._break_next = False
                        self._thread = None
                # Runs may create many short-lived payload/container objects. Collect once
                # at the run boundary; never collect inside the hot loop.
                try:
                    from backend.blocks.ocr_recognize import reset_ocr_engine

                    reset_ocr_engine()
                except Exception:
                    pass
                try:
                    import gc

                    gc.collect()
                except Exception:
                    pass

        thread = threading.Thread(target=worker, daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return {"started": True}

    def pause(self) -> None:
        if not self._running:
            return
        self._pause_event.clear()
        self._emit("flow_paused", {})

    def resume(self) -> None:
        """Continue until next breakpoint (or end)."""
        if not self._running:
            return
        self._break_next = False
        self._step_event.set()
        self._pause_event.set()
        self._emit("flow_resumed", {"via": "continue"})

    def stop(self) -> None:
        """Request stop. Always ends with flow_finished so the UI cannot stick on「停止中」."""
        alive = self._thread_alive()
        running = self._running
        if not running and not alive:
            # Stale Thread object used to make `if not self._thread` fail forever —
            # emit finished so frontend leaves execStatus=stopping.
            self._thread = None
            self._emit("flow_finished", {"ok": False, "error": "当前没有运行中的流程", "stopped": True})
            return

        self._stop_flag.set()
        self._pause_event.set()
        self._step_event.set()
        try:
            from .worker_client import terminate_all_workers

            terminate_all_workers()
        except Exception:
            pass
        self._emit("flow_stopping", {})

        # Worker already gone (or never started) but flags were inconsistent.
        if not alive:
            with self._lock:
                self._running = False
                self._at_breakpoint = False
                self._paused_node_id = None
                self._current_node_id = None
                self._flow_name = ""
                self._debug_mode = False
                self._break_next = False
                self._thread = None
            self._emit("flow_finished", {"ok": False, "error": "已停止", "stopped": True})

    def force_reset(self) -> dict[str, Any]:
        """Abandon the current run immediately so the UI can run again.

        Python cannot forcibly kill a blocked worker thread; we orphan it (bump
        run_id) and mark idle. The old daemon may still finish its current OS
        action, but it can no longer hold interpreter state.
        """
        had_run = bool(self._running or self._thread_alive())
        self._stop_flag.set()
        self._pause_event.set()
        self._step_event.set()
        try:
            from .worker_client import terminate_all_workers

            terminate_all_workers()
        except Exception:
            pass
        with self._lock:
            self._run_id += 1
            self._running = False
            self._at_breakpoint = False
            self._paused_node_id = None
            self._current_node_id = None
            self._flow_name = ""
            self._debug_mode = False
            self._break_next = False
            self._thread = None
        self._emit(
            "flow_finished",
            {
                "ok": False,
                "error": "已强制重置",
                "stopped": True,
                "forced": True,
            },
        )
        return {"had_run": had_run}

    def step(self) -> None:
        """Execute the current / next node, then pause before the following one."""
        if not self._running:
            return
        self._debug_mode = True
        self._break_next = True
        self._step_event.set()
        self._pause_event.set()
        self._emit("flow_stepping", {})

    def wait_until_idle(self, timeout: float | None = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)

    def _snapshot_debug_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        """Compact runtime context for the debug watch panel."""
        if not isinstance(context, dict):
            return {}
        from .runtime_payload import summarize_value

        out: dict[str, Any] = {}
        for key, val in context.items():
            sk = str(key)
            if sk.startswith("__"):
                continue
            # Prefer $name keys; skip bare duplicate of the same value
            if not sk.startswith("$") and f"${sk}" in context:
                continue
            out[sk] = summarize_value(val, key=sk)
            if len(out) >= 120:
                break
        return out

    def _wait_controls(
        self,
        node_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")
        if self._parent_cooperate is not None:
            self._parent_cooperate()
        else:
            self._pause_event.wait()
        if self._is_stop_requested():
            raise InterruptedError("流程已停止")

        if not self._debug_mode:
            return

        reason = None
        if self._break_next:
            reason = "step"
        elif node_id and node_id in self._breakpoints:
            reason = "breakpoint"

        if not reason:
            return

        self._break_next = False
        self._at_breakpoint = True
        self._paused_node_id = node_id
        snap = self._snapshot_debug_context(context)
        self._debug_context = snap
        self._emit(
            "flow_breakpoint",
            {"node_id": node_id, "reason": reason, "context": snap},
        )
        self._step_event.clear()
        self._step_event.wait()
        self._step_event.clear()
        self._at_breakpoint = False
        self._paused_node_id = None
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
        node_index = 0
        global_node_interval = flow.get("__global_node_interval_ms", 0)

        while node_id:
            self._wait_controls(node_id, context)
            node = nodes.get(node_id)
            if not node:
                raise ValueError(f"节点不存在: {node_id}")

            with self._lock:
                self._current_node_id = str(node_id)

            block_type = node.get("type")

            # Disabled nodes: skip handler, follow next (avoid branch/loop side effects).
            if node.get("disabled"):
                self._emit(
                    "node_start",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "params": {},
                        "skipped": True,
                    },
                )
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "result": {"skipped": True},
                        "elapsed_ms": 0,
                        "ok": True,
                        "skipped": True,
                        "summary": f"跳过禁用节点 [{node_id}]",
                        "category": "runtime",
                        "scope": "node",
                    },
                )
                nxt = node.get("next") or None
                if nxt and nxt != node_id:
                    self._emit(
                        "log",
                        {
                            "level": "info",
                            "category": "runtime",
                            "scope": "node",
                            "node_id": node_id,
                            "message": f"禁用跳过 → [{nxt}]",
                            "detail": {"from": node_id, "to": nxt, "type": block_type},
                        },
                    )
                node_id = nxt
                node_index += 1
                continue

            handler = get_handler(block_type)
            if handler is None:
                raise ValueError(f"未知 Block 类型: {block_type}")

            params = resolve_variables(node.get("params") or {}, context)
            wait_ms = node_pre_delay_ms(
                node_index,
                params.get("node_delay_ms"),
                global_node_interval,
            )
            if wait_ms > 0:
                from backend.blocks._helpers import interruptible_sleep

                interruptible_sleep(
                    wait_ms / 1000.0,
                    should_stop=self._is_stop_requested,
                    cooperate=self._cooperate_wait,
                )
            node_index += 1
            self._emit(
                "node_start",
                {
                    "node_id": node_id,
                    "type": block_type,
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
                summarized = summarize_result(result)
                elapsed = round(elapsed_ms, 2)
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "result": summarized,
                        "elapsed_ms": elapsed,
                        "ok": True,
                        "summary": summarize_node_outcome(
                            block_type,
                            ok=True,
                            result=summarized,
                            elapsed_ms=elapsed,
                        ),
                        "category": "runtime",
                        "scope": "node",
                    },
                )
            except InterruptedError:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                elapsed = round(elapsed_ms, 2)
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "error": "已停止",
                        "elapsed_ms": elapsed,
                        "ok": False,
                        "stopped": True,
                        "summary": summarize_node_outcome(
                            block_type, ok=False, error="已停止", elapsed_ms=elapsed, stopped=True
                        ),
                        "category": "runtime",
                        "scope": "node",
                    },
                )
                raise
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                elapsed = round(elapsed_ms, 2)
                self._emit(
                    "node_end",
                    {
                        "node_id": node_id,
                        "type": block_type,
                        "error": str(exc),
                        "elapsed_ms": elapsed,
                        "ok": False,
                        "summary": summarize_node_outcome(
                            block_type, ok=False, error=str(exc), elapsed_ms=elapsed
                        ),
                        "category": "runtime",
                        "scope": "node",
                    },
                )
                raise

            nxt, loop_stack = self.decide_next(
                node, node_id, result, context, nodes, loop_stack
            )
            if nxt and nxt != node_id:
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "category": "runtime",
                        "scope": "node",
                        "node_id": node_id,
                        "message": f"下一跳 → [{nxt}]",
                        "detail": {"from": node_id, "to": nxt, "type": block_type},
                    },
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
            from .expression import compare_values

            params = node.get("params") or {}
            variable = params.get("variable")
            current = resolve_value(variable, context) if variable else None
            current_s = "" if current is None else str(current)

            matched_target: str | None = None
            matched_op = "=="
            matched_rhs = ""
            for case in params.get("cases") or []:
                if not isinstance(case, dict):
                    continue
                raw = case.get("value")
                if raw is None or str(raw).strip() == "":
                    continue
                # Allow {{node.colors.0}} / $var.path as match values
                resolved = resolve_value(raw, context)
                op = str(case.get("op") or "==").strip() or "=="
                if not compare_values(current, resolved, op):
                    continue
                target = str(case.get("node_id") or "").strip()
                if target:
                    matched_target = target
                    matched_op = op
                    matched_rhs = "" if resolved is None else str(resolved)
                break

            if matched_target:
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "message": (
                            f"多分支匹配 → {matched_target}"
                            f"（{current_s!r} {matched_op} {matched_rhs!r}）"
                        ),
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
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "category": "runtime",
                        "scope": "node",
                        "node_id": node_id,
                        "message": f"循环 loop_n 第 {count + 1}/{times} 次",
                        "detail": {"iteration": count + 1, "times": times},
                    },
                )
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
            collection = resolve_value(params.get("collection"), context)
            items = _as_list(collection)
            counter_key = f"__loop_{node_id}__counter"
            count = int(context.get(counter_key, 0))
            if count < len(items):
                item = items[count]
                context[counter_key] = count + 1
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "category": "runtime",
                        "scope": "node",
                        "node_id": node_id,
                        "message": f"循环 foreach 第 {count + 1}/{len(items)} 次",
                        "detail": {"iteration": count + 1, "total": len(items)},
                    },
                )
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
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "category": "runtime",
                        "scope": "node",
                        "node_id": node_id,
                        "message": f"循环 while 第 {count + 1} 次",
                        "detail": {"iteration": count + 1, "max_times": max_times},
                    },
                )
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
