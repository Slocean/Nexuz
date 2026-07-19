"""pywebview JS-Bridge API."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import webview

from backend.core.dpi import get_dpi_scale, screen_size_logical
from backend.core.input.provider_registry import get_provider_registry
from backend.core.input.session import get_recording_session
from backend.core.interpreter import get_interpreter
from backend.core.recorder import get_recorder
from backend.core.registry import (
    get_schemas,
    get_user_blocks_dir as resolve_user_blocks_dir,
    register_all_blocks,
)
from backend.core.runtime_log import get_runtime_log_manager
from backend.core.log_hub import (
    enrich_payload,
    get_app_log_manager,
    build_log_row,
    normalize_category,
)
from backend.core.app_hotkeys import get_app_hotkeys
from backend.core.hotkey_prefs import (
    apply_hotkeys,
    get_all_hotkey_labels,
    get_all_hotkeys,
    get_click_through_hotkey,
    get_click_through_label,
    get_defaults,
    get_pause_run_label,
    get_plugin_mode_label,
    get_start_run_label,
    get_stop_run_label,
)
from backend.core.record_hotkeys import get_record_stop_hotkeys
from backend.core.run_hotkeys import get_run_hotkeys
from backend.core.run_overlay import hide_run_overlay
from backend.paths import (
    default_data_dir,
    exe_dir,
    get_data_dir,
    load_app_config,
    project_root,
    set_data_dir,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None  # type: ignore


class Api:
    def __init__(self):
        self._window: webview.Window | None = None
        register_all_blocks()
        self._schema = self._load_flow_schema()
        self._pick_result: dict[str, Any] | None = None
        self._pick_event = threading.Event()
        self._recording_hidden = False
        self._run_hidden = False
        self._run_monitor_active = False
        self._run_monitor_restore: dict[str, Any] | None = None
        self._run_monitor_flow: dict[str, Any] | None = None
        self._runtime_logs = get_runtime_log_manager()
        self._emit_lock = threading.RLock()
        self._emit_queue: list[dict[str, Any]] = []
        self._emit_stop = threading.Event()
        self._emit_wake = threading.Event()
        self._last_ui_node_event_at = 0.0
        self._last_memory_sample_at = 0.0
        self._emit_thread = threading.Thread(
            target=self._emit_worker, daemon=True, name="nexuz-ui-events"
        )
        self._emit_thread.start()

    def set_window(self, window: webview.Window) -> None:
        self._window = window
        get_interpreter(emit=self._emit)
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        session.set_stop_hotkey_callback(self._on_record_stop_hotkey)

        from backend.core.input.frida.session_manager import get_frida_session_manager

        def on_frida_detached():
            # Stop Frida recording cleanly if process dies mid-record
            sess = get_recording_session()
            if sess.active and sess.mode == "frida_ui":
                try:
                    result = sess.stop()
                    self._emit("recording_stopped", result)
                except Exception:
                    pass

        get_frida_session_manager().set_detached_callback(on_frida_detached)
        get_app_hotkeys().start(
            on_run=self._on_hotkey_run,
            on_plugin_mode=self._on_hotkey_plugin_mode,
        )

        from backend.core.scheduler import get_scheduler

        sched = get_scheduler()
        sched.set_emit(self._emit)
        self._log("info", "窗口就绪，桥接已连接", category="system", scope="app")
        try:
            n = sched.restore_from_disk()
            if n:
                self._log("info", f"已恢复 {n} 个定时任务", category="system", scope="app")
        except Exception as exc:
            self._log("warn", f"恢复定时任务失败: {exc}", category="system", scope="app")
        try:
            get_app_hotkeys()
            self._log("info", "全局热键已注册", category="system", scope="app")
        except Exception as exc:
            self._log("warn", f"热键注册异常: {exc}", category="system", scope="app")

    def _on_hotkey_run(self) -> None:
        """Global start-run hotkey → ask UI to start / continue the current flow."""
        session = get_recording_session()
        if session.active or get_recorder().recording:
            return
        label = get_start_run_label()
        self._emit(
            "hotkey_run",
            {"hotkey": label, "message": f"快捷键开始运行（{label}）"},
        )

    def _on_hotkey_plugin_mode(self) -> None:
        """Global hotkey → toggle plugin / overlay mode."""
        if not self._window:
            return
        label = get_plugin_mode_label()
        result = self.set_plugin_mode({})
        if not result.get("ok"):
            return
        on = bool(result.get("enabled"))
        self._log(
            "info",
            f"快捷键{'开启' if on else '关闭'}插件模式（{label}）",
            category="system",
            scope="app",
        )

    def _on_record_stop_hotkey(self) -> None:
        session = get_recording_session()
        if not session.active and not get_recorder().recording:
            return
        result = self.stop_recording()
        self._emit("recording_stopped", result)

    def get_hotkeys(self) -> dict:
        hotkeys = get_all_hotkeys()
        labels = get_all_hotkey_labels()
        return {
            "ok": True,
            **{slot: keys for slot, keys in hotkeys.items()},
            **{f"{slot}_label": label for slot, label in labels.items()},
            "hotkeys": hotkeys,
            "labels": labels,
            "defaults": get_defaults(),
        }

    def set_hotkeys(self, prefs: dict | None = None) -> dict:
        result = apply_hotkeys(prefs if isinstance(prefs, dict) else {})
        if not result.get("ok"):
            return result
        # Rebind live watchers when prefs change.
        try:
            get_app_hotkeys().restart()
        except Exception:
            pass
        try:
            get_run_hotkeys().restart()
        except Exception:
            pass
        if get_record_stop_hotkeys().active:
            get_record_stop_hotkeys().start(on_stop=self._on_record_stop_hotkey)
        try:
            # Always restart click-through binding when plugin mode is on.
            self._sync_plugin_escape_hotkey(force=True)
        except Exception:
            pass
        hotkeys = result.get("hotkeys") or get_all_hotkeys()
        labels = result.get("labels") or get_all_hotkey_labels()
        return {
            "ok": True,
            **{slot: keys for slot, keys in hotkeys.items()},
            **{f"{slot}_label": label for slot, label in labels.items()},
            "hotkeys": hotkeys,
            "labels": labels,
            "defaults": get_defaults(),
        }

    def _on_run_hotkey_stop(self) -> None:
        interp = get_interpreter()
        if not interp.running:
            return
        label = get_stop_run_label()
        self._emit("log", {"level": "warn", "message": f"快捷键结束流程（{label}）"})
        self.stop_flow()

    def _on_run_hotkey_pause(self) -> None:
        interp = get_interpreter()
        if not interp.running:
            return
        if getattr(interp, "paused", False):
            return
        label = get_pause_run_label()
        self._emit("log", {"level": "warn", "message": f"快捷键暂停流程（{label}）"})
        self.pause_flow()

    def _start_run_controls(self, *, flow: dict | None = None) -> None:
        get_run_hotkeys().start(
            on_stop=self._on_run_hotkey_stop,
            on_pause=self._on_run_hotkey_pause,
        )

    def _stop_run_controls(self) -> None:
        get_run_hotkeys().stop()
        try:
            hide_run_overlay()
        except Exception:
            pass

    def _emit_worker(self) -> None:
        while not self._emit_stop.is_set():
            # Wake early for critical events; otherwise poll every 250ms.
            self._emit_wake.wait(timeout=0.25)
            self._emit_wake.clear()
            if self._emit_stop.is_set():
                break
            self._flush_emit_queue()
            now = time.monotonic()
            if now - self._last_memory_sample_at >= 60.0:
                self._last_memory_sample_at = now
                self._record_memory_sample()

    def _queue_ui_event(self, message: dict[str, Any], *, urgent: bool = False) -> None:
        """Enqueue a UI event. Never call evaluate_js on the pywebview JS-API thread."""
        with self._emit_lock:
            if len(self._emit_queue) >= 500:
                del self._emit_queue[:250]
            self._emit_queue.append(message)
        if urgent:
            self._emit_wake.set()

    def _record_memory_sample(self) -> None:
        try:
            import psutil

            proc = psutil.Process(os.getpid())

            def private_bytes(p) -> int:
                info = p.memory_info()
                return int(getattr(info, "private", getattr(info, "rss", 0)) or 0)

            children = proc.children(recursive=True)
            sample = {
                "category": "diag",
                "scope": "app",
                "level": "debug",
                "message": "memory_sample",
                "python_private_bytes": private_bytes(proc),
                "children_private_bytes": sum(private_bytes(p) for p in children),
                "child_count": len(children),
                "ui_queue": len(self._emit_queue),
            }
            self._runtime_logs.write("memory_sample", sample)
            try:
                get_app_log_manager().write_row(
                    build_log_row("memory_sample", sample, message="memory_sample")
                )
            except Exception:
                pass
        except Exception:
            pass

    def drain_ui_events(self) -> dict:
        """Pull UI events (JS polls). Avoids evaluate_js↔JS-API WebView2 deadlocks."""
        with self._emit_lock:
            messages = self._emit_queue
            self._emit_queue = []
        return {"ok": True, "messages": messages}

    def _flush_emit_queue(self) -> None:
        # Intentionally empty: UI consumes via drain_ui_events().
        # Never call window.evaluate_js here — it deadlocks with in-flight JS API
        # calls (pause/stop) on WebView2/WinForms.
        return

    def _emit(self, event: str, payload: dict) -> None:
        event_payload = enrich_payload(event, dict(payload or {}))
        category = str(event_payload.get("category") or "runtime")

        # Disk: flow session for runtime during a run; app sinks for system/audit/diag
        self._runtime_logs.write(event, event_payload)
        if category in ("system", "audit", "diag"):
            try:
                get_app_log_manager().write_row(
                    build_log_row(
                        event,
                        event_payload,
                        message=event_payload.get("message") or event,
                    )
                )
            except Exception:
                pass

        # UI throttle: successful node ticks while hidden; diag never floods UI unless enabled
        if category == "diag" and not get_app_log_manager().diag_enabled():
            return
        if (
            self._run_hidden
            and event in {"node_start", "node_end"}
            and bool(event_payload.get("ok", True))
            and category == "runtime"
        ):
            now = time.monotonic()
            if now - self._last_ui_node_event_at < 0.5:
                return
            self._last_ui_node_event_at = now
        if event == "flow_finished":
            log_info = self._runtime_logs.finish(event_payload)
            if log_info:
                event_payload["run_log"] = log_info
        message = {"event": event, "payload": event_payload}
        critical = event in {
            "flow_finished",
            "flow_stopping",
            "flow_paused",
            "flow_resumed",
            "flow_breakpoint",
            "force_reset",
            "recording_stopped",
            "schedule_fired",
            "schedule_error",
            "plugin_mode_changed",
        } or (event == "node_end" and not bool(event_payload.get("ok", True)))
        # Queue only — frontend polls drain_ui_events (no evaluate_js push).
        self._queue_ui_event(message, urgent=critical)
        # Window geometry only — UI view switch is owned by the frontend.
        if event in ("flow_finished", "flow_stopped"):
            self._exit_run_monitor()
            if self._run_hidden:
                self._set_window_visible(True)
                self._run_hidden = False

    def _log(
        self,
        level: str,
        message: str,
        *,
        category: str = "system",
        scope: str = "app",
        **detail,
    ) -> None:
        payload: dict[str, Any] = {
            "level": level,
            "message": message,
            "category": normalize_category(category, default="system"),
            "scope": scope,
        }
        if detail:
            # allow explicit category/scope overrides via kwargs already handled
            extra = {k: v for k, v in detail.items() if k not in ("category", "scope")}
            if extra:
                payload["detail"] = extra
        self._emit("log", payload)

    def log_audit(self, message: str, detail=None) -> dict:
        """Persist + emit an audit (editor operation) log line."""
        payload: dict[str, Any] = {
            "category": "audit",
            "level": "info",
            "scope": "flow",
            "message": str(message or ""),
        }
        if detail is not None:
            payload["detail"] = detail
        self._emit("log", payload)
        return {"ok": True}

    def log_system(self, message: str, level: str = "info", detail=None) -> dict:
        payload: dict[str, Any] = {
            "category": "system",
            "level": level,
            "scope": "app",
            "message": str(message or ""),
        }
        if detail is not None:
            payload["detail"] = detail
        self._emit("log", payload)
        return {"ok": True}

    def set_diag_logging(self, enabled: bool = False) -> dict:
        get_app_log_manager().set_diag_enabled(bool(enabled))
        return {"ok": True, "enabled": get_app_log_manager().diag_enabled()}

    def get_diag_logging(self) -> dict:
        return {"ok": True, "enabled": get_app_log_manager().diag_enabled()}

    def export_app_logs(self, categories=None) -> dict:
        """Export system/audit (and optionally diag) app-level JSONL as text."""
        cats = categories if isinstance(categories, list) else ["system", "audit"]
        text = get_app_log_manager().export_text([str(c) for c in cats])
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return self.export_text(text, f"nexuz-app-logs-{stamp}.txt")

    def _load_flow_schema(self) -> dict | None:
        path = project_root() / "schemas" / "flow_schema.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # --- basic ---
    def ping(self) -> dict:
        return {"ok": True, "message": "pong", "dpi_scale": get_dpi_scale()}

    def get_resource_stats(self) -> dict:
        """Live process / host resource snapshot for the toolbar HUD."""
        try:
            import psutil

            proc = psutil.Process(os.getpid())
            with proc.oneshot():
                mem = proc.memory_info()
                rss = int(getattr(mem, "rss", 0) or 0)
                private = int(getattr(mem, "private", rss) or rss)
                cpu = float(proc.cpu_percent(interval=None) or 0.0)
                threads = int(proc.num_threads() or 0)
                create_time = float(proc.create_time() or 0.0)
            children = proc.children(recursive=True)
            child_rss = 0
            for child in children:
                try:
                    child_rss += int(child.memory_info().rss or 0)
                except Exception:
                    pass
            vm = psutil.virtual_memory()
            uptime_s = max(0.0, time.time() - create_time) if create_time else 0.0
            return {
                "ok": True,
                "pid": int(proc.pid),
                "cpu_percent": round(cpu, 1),
                "rss_bytes": rss,
                "private_bytes": private,
                "child_count": len(children),
                "children_rss_bytes": child_rss,
                "threads": threads,
                "uptime_s": round(uptime_s, 1),
                "system_cpu_percent": round(float(psutil.cpu_percent(interval=None) or 0.0), 1),
                "system_mem_percent": round(float(vm.percent or 0.0), 1),
                "system_mem_total_bytes": int(vm.total or 0),
                "system_mem_used_bytes": int(vm.used or 0),
                "ui_queue": len(self._emit_queue),
                "exec_running": bool(get_interpreter().running),
                "ts": time.time(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_block_registry(self) -> list[dict]:
        # Re-scan so newly added blocks appear without restarting the process
        register_all_blocks()
        return get_schemas()

    def get_user_blocks_dir(self) -> dict:
        """Return the user_blocks directory path (created on demand with example)."""
        try:
            path = resolve_user_blocks_dir(create=True)
            return {
                "ok": True,
                "path": str(path),
                "exists": path.is_dir(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": "", "exists": False}

    def open_user_blocks_dir(self) -> dict:
        try:
            path = resolve_user_blocks_dir(create=True)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": ""}
        if not path.is_dir():
            return {"ok": False, "error": "用户积木目录不存在", "path": str(path)}
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": str(path)}

    def _resolve_user_block_file(self, filename: str) -> tuple[Path | None, str | None]:
        """Safe path under user_blocks; only simple *.py names."""
        import re

        name = str(filename or "").strip().replace("\\", "/").split("/")[-1]
        if not re.fullmatch(r"[A-Za-z0-9_\-]+\.py", name):
            return None, "文件名无效（仅允许字母数字_- 与 .py）"
        if name.startswith("_"):
            return None, "以下划线开头的文件不会被加载"
        root = resolve_user_blocks_dir(create=True)
        path = (root / name).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            return None, "路径越界"
        return path, None

    def list_user_block_files(self) -> dict:
        try:
            root = resolve_user_blocks_dir(create=True)
            files = []
            for p in sorted(root.glob("*.py")):
                if p.name.startswith("_"):
                    continue
                files.append({"name": p.name, "path": str(p)})
            return {"ok": True, "path": str(root), "files": files}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "files": []}

    def read_user_block_file(self, filename: str) -> dict:
        path, err = self._resolve_user_block_file(filename)
        if err or path is None:
            return {"ok": False, "error": err or "无效路径", "content": ""}
        if not path.is_file():
            return {"ok": False, "error": "文件不存在", "name": path.name, "content": ""}
        try:
            content = path.read_text(encoding="utf-8")
            return {"ok": True, "name": path.name, "content": content, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "content": ""}

    def write_user_block_file(self, filename: str, content: str = "") -> dict:
        path, err = self._resolve_user_block_file(filename)
        if err or path is None:
            return {"ok": False, "error": err or "无效路径"}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("" if content is None else str(content), encoding="utf-8", newline="\n")
            return {"ok": True, "name": path.name, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def list_schedule_jobs(self) -> dict:
        from backend.core.scheduler import get_scheduler

        sched = get_scheduler()
        return {
            "ok": True,
            "available": sched.available,
            "jobs": sched.list_jobs(),
        }

    def remove_schedule_job(self, job_id: str) -> dict:
        from backend.core.scheduler import get_scheduler

        get_scheduler().remove_job(str(job_id))
        return {"ok": True}

    def get_screen_info(self) -> dict:
        w, h = screen_size_logical()
        return {"width": w, "height": h, "dpi_scale": get_dpi_scale()}

    # --- version / update / announcement ---
    def get_app_info(self) -> dict:
        from backend.version import GITHUB_OWNER, GITHUB_REPO, RELEASES_PAGE_URL, __version__

        frozen = bool(getattr(__import__("sys"), "frozen", False))
        return {
            "ok": True,
            "version": __version__,
            "frozen": frozen,
            "github": f"{GITHUB_OWNER}/{GITHUB_REPO}",
            "releases_url": RELEASES_PAGE_URL,
        }

    def check_for_update(self) -> dict:
        from backend.core.updater import check_for_update

        return check_for_update()

    def fetch_announcement(self) -> dict:
        from backend.core.updater import fetch_announcement

        return fetch_announcement()

    def fetch_notice(self) -> dict:
        from backend.core.updater import fetch_notice

        return fetch_notice()

    def get_notice_read_id(self) -> dict:
        from backend.paths import get_notice_read_id

        return {"ok": True, "id": get_notice_read_id()}

    def set_notice_read_id(self, notice_id: str = "") -> dict:
        from backend.paths import set_notice_read_id

        return {"ok": True, "id": set_notice_read_id(notice_id)}

    def download_update(self, download_url: str | None = None) -> dict:
        from backend.core.updater import download_update

        def on_progress(payload: dict) -> None:
            self._emit("update_download_progress", payload)

        return download_update(download_url, on_progress=on_progress)

    def apply_update(self) -> dict:
        """Downloaded Nexuz_update.exe → detached helper renames over Nexuz.exe and restarts."""
        from backend.core.updater import apply_update_and_restart

        result = apply_update_and_restart()
        if result.get("ok") and result.get("restarting") and self._window:
            # Return to JS first; then exit so the helper can rename/replace the exe.
            def _quit():
                time.sleep(1.2)
                try:
                    self._window.destroy()
                except Exception:
                    pass
                try:
                    os._exit(0)
                except Exception:
                    pass

            threading.Thread(target=_quit, daemon=True).start()
        return result

    def open_releases_page(self) -> dict:
        from backend.core.updater import open_releases_page

        return open_releases_page()

    # --- window chrome (frameless custom title bar) ---
    def window_minimize(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            self._window.minimize()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def window_toggle_maximize(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            maximized = False
            state = getattr(self._window, "state", None)
            # pywebview WindowState may expose maximized
            if state is not None:
                name = getattr(state, "name", str(state))
                maximized = "maximized" in str(name).lower()
            if maximized or getattr(self, "_ui_maximized", False):
                self._window.restore()
                self._ui_maximized = False
                return {"ok": True, "maximized": False}
            self._window.maximize()
            self._ui_maximized = True
            return {"ok": True, "maximized": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def window_close(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            self._window.destroy()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def window_is_maximized(self) -> dict:
        maximized = bool(getattr(self, "_ui_maximized", False))
        try:
            state = getattr(self._window, "state", None) if self._window else None
            if state is not None and "maximized" in str(getattr(state, "name", state)).lower():
                maximized = True
        except Exception:
            pass
        return {"ok": True, "maximized": maximized}

    def window_toggle_on_top(self) -> dict:
        """Toggle always-on-top without freezing the UI.

        pywebview's WinForms ``set_on_top`` assigns ``Form.TopMost`` from the
        JS-API worker thread (no ``Invoke``). That cross-thread UI access
        deadlocks EdgeChromium + frameless windows on Windows. Use Win32
        ``SetWindowPos`` instead, and only sync pywebview's Python flag.
        """
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            if hasattr(self, "_ui_on_top"):
                current = bool(self._ui_on_top)
            else:
                try:
                    current = bool(getattr(self._window, "on_top", False))
                except Exception:
                    current = False
            next_val = not current
            if not self._apply_window_topmost(next_val):
                return {"ok": False, "error": "无法设置窗口置顶", "on_top": current}
            self._ui_on_top = next_val
            self._sync_pywebview_on_top_flag(next_val)
            return {"ok": True, "on_top": next_val}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def window_is_on_top(self) -> dict:
        if hasattr(self, "_ui_on_top"):
            return {"ok": True, "on_top": bool(self._ui_on_top)}
        on_top = False
        try:
            if self._window is not None:
                on_top = bool(getattr(self._window, "on_top", False))
        except Exception:
            on_top = False
        return {"ok": True, "on_top": on_top}

    def window_begin_resize(self, edge: str = "se") -> dict:
        """Resize frameless window from an edge/corner hit zone.

        pywebview JS API is async, so WM_NCLBUTTONDOWN usually misses the still-
        pressed mouse button. Poll cursor + SetWindowPos while LMB is down.
        """
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            maximized = bool(getattr(self, "_ui_maximized", False))
            state = getattr(self._window, "state", None)
            if state is not None and "maximized" in str(getattr(state, "name", state)).lower():
                maximized = True
            if maximized:
                return {"ok": False, "error": "最大化时不可调整大小", "maximized": True}
        except Exception:
            pass

        hwnd = self._window_hwnd()
        if not hwnd:
            return {"ok": False, "error": "无法获取窗口句柄"}

        edge_key = str(edge or "se").strip().lower()
        # Which sides move with the cursor
        move_left = edge_key in ("left", "topleft", "bottomleft", "w", "nw", "sw")
        move_right = edge_key in ("right", "topright", "bottomright", "e", "ne", "se")
        move_top = edge_key in ("top", "topleft", "topright", "n", "nw", "ne")
        move_bottom = edge_key in ("bottom", "bottomleft", "bottomright", "s", "sw", "se")
        if not (move_left or move_right or move_top or move_bottom):
            return {"ok": False, "error": f"无效边缘: {edge}"}

        try:
            import ctypes
            import time
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            # Prefer top-level frame (WebView2 child handle breaks sizing).
            GA_ROOT = 2
            try:
                root = int(user32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOT) or 0)
                if root:
                    hwnd = root
            except Exception:
                pass

            rect = RECT()
            if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
                return {"ok": False, "error": "无法读取窗口矩形"}

            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            start_x, start_y = int(pt.x), int(pt.y)
            orig_l, orig_t = int(rect.left), int(rect.top)
            orig_r, orig_b = int(rect.right), int(rect.bottom)

            min_w, min_h = 800, 560
            try:
                ms = getattr(self._window, "min_size", None) or getattr(self._window, "minsize", None)
                if isinstance(ms, (list, tuple)) and len(ms) >= 2:
                    min_w, min_h = max(1, int(ms[0])), max(1, int(ms[1]))
            except Exception:
                pass

            VK_LBUTTON = 0x01
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            hwnd_p = ctypes.c_void_p(hwnd)

            # Brief wait: bridge latency may arrive before LMB is observed.
            deadline = time.perf_counter() + 0.35
            while not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                if time.perf_counter() >= deadline:
                    return {"ok": False, "error": "未检测到拖动", "edge": edge_key}
                time.sleep(0.008)

            while user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                user32.GetCursorPos(ctypes.byref(pt))
                dx = int(pt.x) - start_x
                dy = int(pt.y) - start_y
                left, top, right, bottom = orig_l, orig_t, orig_r, orig_b
                if move_left:
                    left = min(orig_l + dx, right - min_w)
                if move_right:
                    right = max(orig_r + dx, left + min_w)
                if move_top:
                    top = min(orig_t + dy, bottom - min_h)
                if move_bottom:
                    bottom = max(orig_b + dy, top + min_h)
                user32.SetWindowPos(
                    hwnd_p,
                    None,
                    int(left),
                    int(top),
                    int(right - left),
                    int(bottom - top),
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                time.sleep(0.008)

            # Sync pywebview cached size/position when possible.
            try:
                w = self._window
                if w is not None and user32.GetWindowRect(hwnd_p, ctypes.byref(rect)):
                    for attr, val in (
                        ("x", int(rect.left)),
                        ("y", int(rect.top)),
                        ("width", int(rect.right - rect.left)),
                        ("height", int(rect.bottom - rect.top)),
                    ):
                        try:
                            object.__setattr__(w, attr, val)
                        except Exception:
                            pass
            except Exception:
                pass

            return {"ok": True, "edge": edge_key}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _window_hwnd(self) -> int | None:
        w = self._window
        if w is None:
            return None
        native = getattr(w, "native", None)
        if native is not None:
            try:
                handle = getattr(native, "Handle", None)
                if handle is not None:
                    to_int = getattr(handle, "ToInt32", None)
                    if callable(to_int):
                        return int(to_int())
                    to_int64 = getattr(handle, "ToInt64", None)
                    if callable(to_int64):
                        return int(to_int64())
                    return int(handle)
            except Exception:
                pass
        for attr in ("hwnd", "handle"):
            try:
                h = getattr(w, attr, None)
                if h is not None:
                    return int(h)
            except Exception:
                pass
        return None

    def _apply_window_topmost(self, on_top: bool) -> bool:
        hwnd = self._window_hwnd()
        if hwnd:
            try:
                import ctypes

                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                ok = ctypes.windll.user32.SetWindowPos(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_void_p(HWND_TOPMOST if on_top else HWND_NOTOPMOST),
                    0,
                    0,
                    0,
                    0,
                    flags,
                )
                if ok:
                    return True
            except Exception:
                pass

        # Non-Windows / hwnd unavailable: defer pywebview setter so JS bridge can return.
        window = self._window
        if window is None:
            return False

        def _apply() -> None:
            try:
                window.on_top = on_top
            except Exception:
                pass

        threading.Thread(target=_apply, daemon=True).start()
        return True

    def _sync_pywebview_on_top_flag(self, on_top: bool) -> None:
        """Update pywebview's cached flag without calling the WinForms setter."""
        w = self._window
        if w is None:
            return
        try:
            # name-mangled storage for Window.on_top
            object.__setattr__(w, "_Window__on_top", bool(on_top))
        except Exception:
            try:
                w.__dict__["_Window__on_top"] = bool(on_top)
            except Exception:
                pass

    def _root_hwnd(self) -> int | None:
        """Top-level frame hwnd (WebView2 child handle breaks layered styles)."""
        hwnd = self._window_hwnd()
        if not hwnd:
            return None
        try:
            import ctypes

            GA_ROOT = 2
            root = int(ctypes.windll.user32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOT) or 0)
            return root or hwnd
        except Exception:
            return hwnd

    def _layered_hwnds(self) -> list[int]:
        """Candidate top-level hwnds for layered alpha (Form + GA_ROOT)."""
        seen: set[int] = set()
        out: list[int] = []
        for hwnd in (self._root_hwnd(), self._window_hwnd()):
            if not hwnd or hwnd in seen:
                continue
            seen.add(hwnd)
            out.append(int(hwnd))
        return out

    def _apply_window_opacity(self, opacity: float) -> bool:
        """Whole-window alpha via WS_EX_LAYERED + LWA_ALPHA (Windows).

        Must run *after* any SetWindowLong(GWL_EXSTYLE) — changing exstyle
        clears layered attributes. Also try WinForms Form.Opacity when safe.
        """
        try:
            # Allow 1.0 when restoring; plugin UI clamps to >=0.25 separately.
            opacity_f = max(0.05, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            opacity_f = 0.85
        alpha = max(13, min(255, int(round(opacity_f * 255))))

        # Prefer Form.Opacity on the UI thread when available (WebView2-friendly).
        applied_form = False
        try:
            native = getattr(self._window, "native", None) if self._window else None
            if native is not None and hasattr(native, "Opacity"):

                def _set() -> None:
                    try:
                        native.Opacity = float(opacity_f)
                    except Exception:
                        pass

                try:
                    invoke_required = bool(getattr(native, "InvokeRequired", False))
                except Exception:
                    invoke_required = False
                if invoke_required and hasattr(native, "BeginInvoke"):
                    try:
                        from System import Action  # type: ignore

                        native.BeginInvoke(Action(_set))
                        applied_form = True
                    except Exception:
                        _set()
                        applied_form = True
                else:
                    _set()
                    applied_form = True
        except Exception:
            applied_form = False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            LWA_ALPHA = 0x02
            if hasattr(user32, "GetWindowLongPtrW"):
                get_long = user32.GetWindowLongPtrW
                set_long = user32.SetWindowLongPtrW
            else:
                get_long = user32.GetWindowLongW
                set_long = user32.SetWindowLongW
            try:
                user32.SetLayeredWindowAttributes.argtypes = [
                    wintypes.HWND,
                    wintypes.COLORREF,
                    wintypes.BYTE,
                    wintypes.DWORD,
                ]
                user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            except Exception:
                pass

            ok_any = False
            for hwnd in self._layered_hwnds():
                hwnd_p = ctypes.c_void_p(hwnd)
                style = int(get_long(hwnd_p, GWL_EXSTYLE) or 0)
                set_long(hwnd_p, GWL_EXSTYLE, style | WS_EX_LAYERED)
                ok = bool(user32.SetLayeredWindowAttributes(hwnd_p, 0, alpha, LWA_ALPHA))
                ok_any = ok_any or ok
            return ok_any or applied_form
        except Exception:
            return applied_form

    def _apply_click_through(self, enabled: bool) -> bool:
        """WS_EX_TRANSPARENT: mouse goes to windows below (game).

        Caller must re-apply window opacity afterwards — SetWindowLong on
        GWL_EXSTYLE drops previous SetLayeredWindowAttributes alpha.
        """
        hwnds = self._layered_hwnds()
        if not hwnds:
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            if hasattr(user32, "GetWindowLongPtrW"):
                get_long = user32.GetWindowLongPtrW
                set_long = user32.SetWindowLongPtrW
            else:
                get_long = user32.GetWindowLongW
                set_long = user32.SetWindowLongW
            for hwnd in hwnds:
                hwnd_p = ctypes.c_void_p(hwnd)
                style = int(get_long(hwnd_p, GWL_EXSTYLE) or 0)
                style |= WS_EX_LAYERED
                if enabled:
                    style |= WS_EX_TRANSPARENT
                else:
                    style &= ~WS_EX_TRANSPARENT
                set_long(hwnd_p, GWL_EXSTYLE, style)
            return True
        except Exception:
            return False

    def _stop_plugin_escape_hotkey(self) -> None:
        listener = getattr(self, "_plugin_hotkey_listener", None)
        self._plugin_hotkey_listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass

    def _start_plugin_escape_hotkey(self) -> None:
        """Toggle click-through while plugin mode is on (default X+F7, user-configurable)."""
        self._stop_plugin_escape_hotkey()
        try:
            from pynput import keyboard
        except Exception:
            return
        from backend.core.hotkey_prefs import to_pynput_hotkey

        binding = to_pynput_hotkey(get_click_through_hotkey(), default=("x", "f7"))
        ct_label = get_click_through_label()

        def on_toggle() -> None:
            if not getattr(self, "_plugin_mode", False):
                return
            now = time.monotonic()
            last = float(getattr(self, "_plugin_hotkey_last", 0.0) or 0.0)
            if now - last < 0.4:
                return
            self._plugin_hotkey_last = now
            nxt = not bool(getattr(self, "_plugin_click_through", False))
            self.set_plugin_mode(
                {
                    "enabled": True,
                    "opacity": float(getattr(self, "_plugin_opacity", 0.85)),
                    "click_through": nxt,
                }
            )
            self._log(
                "info",
                f"快捷键打开点击穿透（{ct_label}）"
                if nxt
                else f"快捷键关闭点击穿透（{ct_label}）",
            )

        try:
            listener = keyboard.GlobalHotKeys({binding: on_toggle})
            listener.start()
            self._plugin_hotkey_listener = listener
        except Exception:
            self._plugin_hotkey_listener = None

    def _sync_plugin_escape_hotkey(self, force: bool = False) -> None:
        if getattr(self, "_plugin_mode", False):
            if force or getattr(self, "_plugin_hotkey_listener", None) is None:
                self._start_plugin_escape_hotkey()
        else:
            self._stop_plugin_escape_hotkey()

    def set_plugin_mode(self, options=None) -> dict:
        """
        Overlay / plugin mode: float above games with adjustable opacity.

        options: {enabled?, opacity? (0.25–1), click_through?}
        Uses Win32 layered window + topmost(NOACTIVATE). Best with borderless
        fullscreen; exclusive fullscreen may still minimize when you focus Nexuz.
        While enabled, the click_through hotkey (default X+F7) toggles pass-through.
        """
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        opts = options if isinstance(options, dict) else {}
        enabled = bool(opts["enabled"]) if "enabled" in opts else not bool(
            getattr(self, "_plugin_mode", False)
        )
        try:
            opacity = float(opts.get("opacity", getattr(self, "_plugin_opacity", 0.85)))
        except (TypeError, ValueError):
            opacity = 0.85
        opacity = max(0.25, min(1.0, opacity))
        click_through = bool(opts.get("click_through", getattr(self, "_plugin_click_through", False)))
        ct_label = get_click_through_label()
        pm_label = get_plugin_mode_label()

        if enabled:
            if not getattr(self, "_plugin_mode", False):
                # Remember prior pin state
                self._plugin_prev_on_top = bool(getattr(self, "_ui_on_top", False))
            if not self._apply_window_topmost(True):
                return {"ok": False, "error": "无法置顶窗口"}
            self._ui_on_top = True
            self._sync_pywebview_on_top_flag(True)
            # Exstyle changes wipe layered alpha — always opacity last.
            self._apply_click_through(click_through)
            if not self._apply_window_opacity(opacity):
                return {"ok": False, "error": "无法设置窗口透明度（需 Windows）"}
            self._plugin_mode = True
            self._plugin_opacity = opacity
            self._plugin_click_through = click_through
        else:
            self._apply_click_through(False)
            # Restore full opacity (Form.Opacity + layered alpha)
            self._apply_window_opacity(1.0)
            try:
                native = getattr(self._window, "native", None) if self._window else None
                if native is not None and hasattr(native, "Opacity"):
                    def _reset() -> None:
                        try:
                            native.Opacity = 1.0
                        except Exception:
                            pass

                    try:
                        if bool(getattr(native, "InvokeRequired", False)) and hasattr(
                            native, "BeginInvoke"
                        ):
                            from System import Action  # type: ignore

                            native.BeginInvoke(Action(_reset))
                        else:
                            _reset()
                    except Exception:
                        _reset()
            except Exception:
                pass
            restore_top = bool(getattr(self, "_plugin_prev_on_top", False))
            self._apply_window_topmost(restore_top)
            self._ui_on_top = restore_top
            self._sync_pywebview_on_top_flag(restore_top)
            self._plugin_mode = False
            self._plugin_opacity = opacity
            self._plugin_click_through = False

        self._sync_plugin_escape_hotkey(force=True)
        result = {
            "ok": True,
            "enabled": bool(self._plugin_mode),
            "opacity": float(getattr(self, "_plugin_opacity", opacity)),
            "click_through": bool(getattr(self, "_plugin_click_through", False)),
            "on_top": bool(getattr(self, "_ui_on_top", False)),
            "escape_hotkey": ct_label,
            "plugin_mode_hotkey": pm_label,
            "hint": (
                "插件模式已开启：窗口浮在最前且半透明。"
                "无边框全屏游戏通常可用；独占全屏在点到本窗口时仍可能退出全屏。"
                f"需要操作游戏时请打开「点击穿透」；按 {ct_label} 可开关穿透。"
                f"（开关插件模式：{pm_label}）"
                if self._plugin_mode
                else "已退出插件模式"
            ),
        }
        # Avoid re-entrant emit loop when hotkey calls set_plugin_mode
        if not bool(opts.get("_silent")):
            try:
                self._emit("plugin_mode_changed", {k: v for k, v in result.items() if k != "hint"})
            except Exception:
                pass
        return result

    def get_plugin_mode(self) -> dict:
        return {
            "ok": True,
            "enabled": bool(getattr(self, "_plugin_mode", False)),
            "opacity": float(getattr(self, "_plugin_opacity", 0.85)),
            "click_through": bool(getattr(self, "_plugin_click_through", False)),
            "on_top": bool(getattr(self, "_ui_on_top", False)),
            "escape_hotkey": get_click_through_label(),
            "plugin_mode_hotkey": get_plugin_mode_label(),
        }

    # --- flow execution ---
    def run_flow(
        self,
        flow_json: str,
        step_mode: bool = False,
        hide_window: bool = True,
        debug_mode: bool = False,
        breakpoints=None,
    ) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        interp = get_interpreter(emit=self._emit)

        bps = breakpoints
        if isinstance(bps, str):
            try:
                bps = json.loads(bps)
            except Exception:
                bps = None
        if bps is None:
            bps = flow.get("breakpoints")
        if not isinstance(bps, list):
            bps = []

        # If a session is already paused / at breakpoint, resume it — do not hide / restart.
        if interp.running and getattr(interp, "paused", False):
            try:
                result = interp.run_flow(
                    flow,
                    step_mode=bool(step_mode),
                    debug_mode=bool(debug_mode) or bool(step_mode),
                    breakpoints=bps,
                )
                return {"ok": True, "resumed": True, **(result or {})}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # Continuous run + hideWindow → compact main-window monitor (not hide + Tk).
        # Debug / step keeps the full editor UI.
        in_debug = bool(debug_mode) or bool(step_mode)
        use_monitor = bool(hide_window) and not in_debug
        log_session = self._runtime_logs.start(flow)
        self._run_hidden = False
        try:
            result = interp.run_flow(
                flow,
                step_mode=bool(step_mode),
                debug_mode=in_debug,
                breakpoints=bps,
            )
            started = bool((result or {}).get("started", True))
            resumed = bool((result or {}).get("resumed"))
            if started and not resumed:
                if use_monitor:
                    # Geometry + hotkeys only; frontend flips to RunMonitorView.
                    self._enter_run_monitor(flow)
                else:
                    self._start_run_controls(flow=flow)
                self._emit(
                    "log",
                    {
                        "level": "info",
                        "message": (
                            f"运行热键：暂停 {get_pause_run_label()} · 结束 {get_stop_run_label()}"
                        ),
                    },
                )
            return {
                "ok": True,
                "started": started,
                "resumed": resumed,
                "hide_window": False,
                "run_monitor": use_monitor,
                "debug_mode": in_debug,
                "run_log": log_session.info(),
            }
        except Exception as exc:
            self._runtime_logs.finish({"ok": False, "error": str(exc)})
            self._exit_run_monitor()
            return {"ok": False, "error": str(exc)}

    def pause_flow(self) -> dict:
        """Same path for editor and run-monitor UI — only pauses the interpreter."""
        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.pause()
        return {"ok": True, "paused": True}

    def resume_flow(self) -> dict:
        """Same path for editor and run-monitor UI — only resumes the interpreter."""
        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.resume()
        return {"ok": True, "resumed": True}

    def continue_flow(self) -> dict:
        """Alias: continue until next breakpoint."""
        return self.resume_flow()

    def stop_flow(self) -> dict:
        """Same path for editor and run-monitor UI — only stops the interpreter."""
        get_interpreter().stop()
        return {"ok": True, "stopping": True}

    def force_reset(self) -> dict:
        """Universal recovery: clear run / record / overlays so the app is runnable again."""
        cleared: list[str] = []
        try:
            info = get_interpreter(emit=self._emit).force_reset()
            if info.get("had_run"):
                cleared.append("flow")
        except Exception:
            pass

        try:
            get_record_stop_hotkeys().stop()
        except Exception:
            pass
        try:
            session = get_recording_session(
                set_window_visible=self._set_window_visible,
                emit=self._emit,
            )
            if session.active or get_recorder().recording:
                # Stop without appending nodes to the canvas.
                if session.active:
                    session.stop()
                elif get_recorder().recording:
                    get_recorder().stop()
                cleared.append("recording")
                self._emit(
                    "recording_stopped",
                    {"ok": True, "nodes": [], "forced": True, "mode": "coord"},
                )
        except Exception:
            pass

        try:
            from backend.core.record_overlay import hide_stop_overlay

            hide_stop_overlay()
        except Exception:
            pass
        self._exit_run_monitor()
        self._set_window_visible(True)
        self._run_hidden = False
        self._recording_hidden = False

        forced_log = self._runtime_logs.finish(
            {"ok": False, "forced": True, "error": "流程状态已强制重置"}
        )
        force_payload: dict[str, Any] = {"cleared": cleared}
        if forced_log:
            force_payload["run_log"] = forced_log
        self._emit("force_reset", force_payload)
        return {
            "ok": True,
            "cleared": cleared,
            "message": "已强制重置，可以重新运行"
            + (f"（清理：{'、'.join(cleared)}）" if cleared else "（状态已空闲）"),
        }

    def step_flow(self) -> dict:
        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.step()
        if self._run_hidden:
            self._set_window_visible(True)
            self._run_hidden = False
        return {"ok": True}

    def set_breakpoints(self, node_ids=None) -> dict:
        ids = node_ids
        if isinstance(ids, str):
            try:
                ids = json.loads(ids)
            except Exception:
                ids = [ids] if ids.strip() else []
        if not isinstance(ids, list):
            ids = []
        get_interpreter().set_breakpoints(ids)
        return {"ok": True, "breakpoints": [str(x) for x in ids if str(x).strip()]}

    def is_running(self) -> dict:
        interp = get_interpreter()
        return {
            "running": interp.running,
            "paused": bool(getattr(interp, "paused", False)),
            "at_breakpoint": bool(getattr(interp, "at_breakpoint", False)),
            "debug_mode": bool(getattr(interp, "debug_mode", False)),
        }

    # --- user data directory (AppData by default) ---
    def _data_root(self, *, create: bool = False) -> Path:
        return get_data_dir(create=create)

    def _flows_dir(self, *, create: bool = False) -> Path:
        d = self._data_root(create=create) / "flows"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def _flow_templates_dir(self, *, create: bool = False) -> Path:
        d = self._data_root(create=create) / "flow_templates"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def _templates_dir(self, *, create: bool = False) -> Path:
        d = self._data_root(create=create) / "templates"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def _is_under_dir(self, path: Path, folder: Path) -> bool:
        try:
            resolved = path.resolve()
            root = folder.resolve()
        except Exception:
            return False
        return root in resolved.parents or resolved.parent == root

    def _migrate_legacy_user_data(self) -> None:
        """One-shot: copy exe-side flows/templates into AppData if target is empty."""
        try:
            cfg = load_app_config()
            if cfg.get("migrated_from_exe"):
                return
            dest_root = self._data_root(create=False)
            pairs = [
                (exe_dir() / "flows", dest_root / "flows"),
                (exe_dir() / "flow_templates", dest_root / "flow_templates"),
                (exe_dir() / "templates", dest_root / "templates"),
            ]
            migrated_any = False
            for src, dest in pairs:
                if not src.is_dir():
                    continue
                files = [p for p in src.iterdir() if p.is_file()]
                if not files:
                    continue
                if dest.exists() and any(dest.iterdir()):
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                import shutil

                for f in files:
                    target = dest / f.name
                    if not target.exists():
                        shutil.copy2(f, target)
                        migrated_any = True
            cfg = load_app_config()
            cfg["migrated_from_exe"] = True
            from backend.paths import save_app_config

            save_app_config(cfg)
            if migrated_any:
                pass
        except Exception:
            pass

    def get_data_dir_info(self) -> dict:
        self._migrate_legacy_user_data()
        root = self._data_root(create=False)
        default = default_data_dir()
        cfg = load_app_config()
        custom = bool(cfg.get("data_dir"))
        return {
            "ok": True,
            "path": str(root),
            "exists": root.is_dir(),
            "default_path": str(default),
            "is_default": not custom,
        }

    def pick_data_dir(self) -> dict:
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        current = self._data_root(create=False)
        start = str(current if current.is_dir() else current.parent)
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=start,
            allow_multiple=False,
        )
        if not result:
            return {"ok": False, "cancelled": True}
        folder = result[0] if isinstance(result, (list, tuple)) else result
        path = set_data_dir(folder)
        return {"ok": True, "path": str(path), "exists": path.is_dir(), "is_default": False}

    def set_data_dir_path(self, path: str | None = None) -> dict:
        """Set custom data dir, or pass empty/None to reset to default AppData."""
        try:
            root = set_data_dir(path)
            return {
                "ok": True,
                "path": str(root),
                "exists": root.is_dir(),
                "is_default": not bool(path and str(path).strip()),
                "default_path": str(default_data_dir()),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_data_dir(self) -> dict:
        root = self._data_root(create=False)
        if not root.is_dir():
            return {
                "ok": False,
                "error": "数据目录不存在（可能已清空；保存流程后会自动创建）",
                "path": str(root),
            }
        try:
            os.startfile(str(root))  # type: ignore[attr-defined]
            return {"ok": True, "path": str(root)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": str(root)}

    def clear_data_dir(self) -> dict:
        """Delete the entire data directory tree. Recreated only on next save."""
        import shutil

        root = self._data_root(create=False)
        path_str = str(root)
        if not root.exists():
            return {"ok": True, "path": path_str, "deleted": False, "message": "目录本就不存在"}
        try:
            # If config lives inside the data root, preserve data_dir preference then wipe.
            cfg = load_app_config()
            custom = cfg.get("data_dir")
            shutil.rmtree(root)
            # Recreate config-only stub under default AppData when we wiped the default root.
            if custom:
                set_data_dir(custom)
            else:
                # default root deleted (incl. config) — nothing to restore
                pass
            return {"ok": True, "path": path_str, "deleted": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": path_str}

    def clear_screenshot_cache(self) -> dict:
        """Delete cached screenshots / match previews under data_dir/screenshots/.

        Does not touch flows, templates/, or other user data.
        """
        folder = self._data_root(create=False) / "screenshots"
        if not folder.is_dir():
            return {
                "ok": True,
                "path": str(folder),
                "deleted": 0,
                "bytes": 0,
                "message": "没有可清理的截图缓存",
            }
        deleted = 0
        freed = 0
        errors: list[str] = []
        try:
            for entry in folder.iterdir():
                if not entry.is_file():
                    continue
                try:
                    freed += int(entry.stat().st_size)
                    entry.unlink()
                    deleted += 1
                except OSError as exc:
                    errors.append(f"{entry.name}: {exc}")
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": str(folder)}
        mb = freed / (1024 * 1024)
        msg = f"已清理 {deleted} 个文件（约 {mb:.1f} MB）"
        if errors:
            msg += f"；{len(errors)} 个失败"
        return {
            "ok": True,
            "path": str(folder),
            "deleted": deleted,
            "bytes": freed,
            "errors": errors[:5],
            "message": msg,
        }

    @staticmethod
    def _safe_flow_filename(name: str) -> str:
        raw = (name or "未命名流程").strip() or "未命名流程"
        safe = "".join(c if c.isalnum() or c in ("-", "_", " ", ".", "（", "）", "【", "】") else "_" for c in raw)
        safe = "_".join(safe.split())
        if not safe.lower().endswith(".flow.json"):
            if safe.lower().endswith(".json"):
                safe = safe[: -5] + ".flow.json"
            else:
                safe = f"{safe}.flow.json"
        return safe

    def _unique_flow_path(self, name: str) -> Path:
        folder = self._flows_dir(create=True)
        base = self._safe_flow_filename(name)
        path = folder / base
        if not path.exists():
            return path
        stem = base[: -len(".flow.json")] if base.lower().endswith(".flow.json") else Path(base).stem
        for i in range(2, 1000):
            candidate = folder / f"{stem}_{i}.flow.json"
            if not candidate.exists():
                return candidate
        return folder / f"{stem}_{int(time.time())}.flow.json"

    def list_flows(self) -> dict:
        """List flows in the user data library."""
        self._migrate_legacy_user_data()
        items = []
        folder = self._flows_dir(create=False)
        if not folder.is_dir():
            return {"ok": True, "flows": [], "dir": str(folder), "exists": False}
        for path in sorted(folder.glob("*.flow.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = path.stem.replace(".flow", "") if path.name.endswith(".flow.json") else path.stem
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = data.get("name") or name
            except Exception:
                data = None
            st = path.stat()
            items.append(
                {
                    "name": name,
                    "path": str(path),
                    "mtime": int(st.st_mtime * 1000),
                    "size": st.st_size,
                }
            )
        return {"ok": True, "flows": items, "dir": str(folder), "exists": True}

    def rename_flow(self, filepath: str, new_name: str) -> dict:
        """Update a flow's display name without moving its file.

        Keeping the path stable prevents existing subflow and schedule references
        from breaking when a user renames a library entry.
        """
        path = Path(str(filepath))
        flows = self._flows_dir(create=False)
        name = str(new_name or "").strip()
        if not name:
            return {"ok": False, "error": "流程名称不能为空"}
        try:
            if not flows.is_dir() or not self._is_under_dir(path, flows):
                return {"ok": False, "error": "只能重命名数据目录内的流程"}
            resolved = path.resolve()
            if not resolved.is_file():
                return {"ok": False, "error": "流程文件不存在"}
            flow = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(flow, dict):
                return {"ok": False, "error": "无效的流程对象"}
            flow["name"] = name
            temp = resolved.with_suffix(resolved.suffix + ".tmp")
            temp.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(resolved)
            return {"ok": True, "path": str(resolved), "name": name}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_flow(self, filepath: str) -> dict:
        path = Path(str(filepath))
        flows = self._flows_dir(create=False)
        try:
            if not flows.is_dir() or not self._is_under_dir(path, flows):
                return {"ok": False, "error": "只能删除数据目录内的流程"}
            resolved = path.resolve()
            if not resolved.is_file():
                return {"ok": False, "error": "文件不存在"}
            resolved.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # --- flow templates library (流程模板，不同于截图 templates/) ---
    def list_flow_templates(self) -> dict:
        """List user-saved flow templates under data_dir/flow_templates."""
        self._migrate_legacy_user_data()
        items = []
        folder = self._flow_templates_dir(create=False)
        if not folder.is_dir():
            return {"ok": True, "templates": [], "dir": str(folder)}
        for path in sorted(folder.glob("*.flow.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            name = path.stem.replace(".flow", "") if path.name.endswith(".flow.json") else path.stem
            description = ""
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = data.get("name") or name
                description = str(data.get("description") or data.get("template_description") or "")
            except Exception:
                data = None
            st = path.stat()
            items.append(
                {
                    "id": path.stem,
                    "name": name,
                    "description": description,
                    "path": str(path),
                    "mtime": int(st.st_mtime * 1000),
                    "size": st.st_size,
                    "builtin": False,
                }
            )
        return {"ok": True, "templates": items, "dir": str(folder)}

    def save_flow_template(self, flow_json: str, name: str | None = None, description: str | None = None) -> dict:
        """Save current flow as a reusable template under flow_templates/."""
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if not isinstance(flow, dict):
            return {"ok": False, "error": "无效的流程对象"}
        tpl_name = (str(name).strip() if name else "") or str(flow.get("name") or "").strip() or "未命名模板"
        flow = {**flow, "name": tpl_name}
        desc = (str(description).strip() if description else "") or str(flow.get("description") or "").strip()
        if desc:
            flow["description"] = desc
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        path = self._flow_templates_dir(create=True) / self._safe_flow_filename(tpl_name)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": tpl_name}

    def delete_flow_template(self, filepath: str) -> dict:
        path = Path(str(filepath))
        folder = self._flow_templates_dir(create=False)
        try:
            if not folder.is_dir() or not self._is_under_dir(path, folder):
                return {"ok": False, "error": "只能删除数据目录内的模板"}
            resolved = path.resolve()
            if not resolved.is_file():
                return {"ok": False, "error": "文件不存在"}
            resolved.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def load_flow_template(self, filepath: str) -> dict:
        """Load a flow template by path (must be under flow_templates/)."""
        path = Path(str(filepath))
        folder = self._flow_templates_dir(create=False)
        try:
            if not folder.is_dir() or not self._is_under_dir(path, folder):
                return {"ok": False, "error": "只能加载数据目录内的模板"}
            resolved = path.resolve()
            if not resolved.is_file():
                return {"ok": False, "error": "模板不存在"}
            data = json.loads(resolved.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        err = self._validate_flow(data)
        if err:
            return {"ok": False, "error": err, "path": str(path)}
        return {"ok": True, "flow": data, "path": str(path)}

    def save_flow(self, flow_json: str, filepath: str | None = None, name: str | None = None) -> dict:
        """Save into the user data library (creates data dir if needed)."""
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if not isinstance(flow, dict):
            return {"ok": False, "error": "无效的流程对象"}
        if name and str(name).strip():
            flow = {**flow, "name": str(name).strip()}

        if filepath:
            path = Path(str(filepath))
            flows = self._flows_dir(create=True)
            if not self._is_under_dir(path, flows):
                # Legacy path outside library → save as new library entry by name
                flow_name = str(flow.get("name") or name or "").strip() or "未命名流程"
                path = flows / self._safe_flow_filename(flow_name)
        else:
            flow_name = str(flow.get("name") or name or "").strip()
            if not flow_name:
                return {"ok": False, "error": "请先为流程命名"}
            path = self._flows_dir(create=True) / self._safe_flow_filename(flow_name)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": flow.get("name")}

    def export_flow(self, flow_json: str, filename: str | None = None) -> dict:
        """Export flow as JSON or portable .flow.zip (includes template images)."""
        from backend.core.flow_pack import build_zip_bytes, flow_has_packable_assets, is_zip_path

        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if not isinstance(flow, dict):
            return {"ok": False, "error": "无效的流程对象"}
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        base_name = (filename or flow.get("name") or "flow").strip() or "flow"
        safe_json = self._safe_flow_filename(base_name)
        base = safe_json.replace(".flow.json", "").replace(".json", "") or "flow"
        prefer_zip = flow_has_packable_assets(flow)
        suggested = f"{base}.flow.zip" if prefer_zip else safe_json
        if not self._window:
            out_dir = exe_dir() / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            if prefer_zip:
                out = out_dir / f"{base}.flow.zip"
                out.write_bytes(build_zip_bytes(flow))
                return {"ok": True, "path": str(out), "name": flow.get("name"), "format": "zip"}
            out = out_dir / self._safe_flow_filename(base)
            out.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "path": str(out), "name": flow.get("name"), "format": "json"}
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(exe_dir()),
            save_filename=suggested,
            file_types=(
                "流程包 Zip (*.flow.zip;*.zip)",
                "Flow JSON (*.flow.json;*.json)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        filepath = result if isinstance(result, str) else result[0]
        path = Path(filepath)
        lower = path.name.lower()
        as_zip = is_zip_path(path) or lower.endswith(".zip")
        if not as_zip and not lower.endswith(".json"):
            # User typed bare name: pick zip when assets exist
            if prefer_zip:
                path = path.with_name(path.name + ".flow.zip")
                as_zip = True
            else:
                path = path.with_name(path.name + ".flow.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if as_zip:
            path.write_bytes(build_zip_bytes(flow))
            return {"ok": True, "path": str(path), "name": flow.get("name"), "format": "zip"}
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": flow.get("name"), "format": "json"}

    def import_flow(self) -> dict:
        """Import external .flow.json or .flow.zip into the user data library."""
        from backend.core.flow_pack import is_zip_path, load_flow_from_zip

        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=str(exe_dir()),
            allow_multiple=False,
            file_types=(
                "流程文件 (*.flow.zip;*.zip;*.flow.json;*.json)",
                "流程包 Zip (*.flow.zip;*.zip)",
                "Flow JSON (*.flow.json;*.json)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        src = result[0] if isinstance(result, (list, tuple)) else result
        src_path = Path(src)
        if not src_path.exists():
            return {"ok": False, "error": f"文件不存在: {src}"}
        try:
            if is_zip_path(src_path):
                templates = self._templates_dir(create=True)

                def _import_img(raw: bytes, preferred: str | None):
                    return self._import_image_bytes_to_templates(raw, preferred)

                data = load_flow_from_zip(
                    src_path,
                    templates_dir=templates,
                    import_image=_import_img,
                )
                fmt = "zip"
            else:
                data = json.loads(src_path.read_text(encoding="utf-8"))
                fmt = "json"
        except Exception as exc:
            return {"ok": False, "error": f"无法解析流程文件: {exc}"}
        err = self._validate_flow(data)
        if err:
            return {"ok": False, "error": err}
        stem = src_path.stem
        if stem.lower().endswith(".flow"):
            stem = stem[:-5]
        name = str(data.get("name") or stem or "导入的流程").strip()
        data = {**data, "name": name}
        dest = self._unique_flow_path(name)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "flow": data, "path": str(dest), "name": name, "format": fmt}

    def clipboard_write(self, text: str) -> dict:
        """Copy text to system clipboard (pywebview often blocks navigator.clipboard)."""
        from backend.blocks._system_io import clipboard_write as _clipboard_write

        res = _clipboard_write("" if text is None else str(text))
        if res.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": res.get("error") or "剪贴板写入失败"}

    def read_local_image(self, filepath: str) -> dict:
        """Read a local image as data URL for Inspector preview (size-capped)."""
        import base64

        path = Path(str(filepath or "")).expanduser()
        try:
            path = path.resolve()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not path.is_file():
            return {"ok": False, "error": "文件不存在"}
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime = mime_map.get(path.suffix.lower())
        if not mime:
            return {"ok": False, "error": "不支持的图片格式"}
        max_bytes = 12 * 1024 * 1024
        try:
            size = path.stat().st_size
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if size <= 0:
            return {"ok": False, "error": "空文件"}
        if size > max_bytes:
            return {"ok": False, "error": "图片过大，无法预览"}
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        return {"ok": True, "data_url": data_url, "path": str(path), "size": size}

    def _unique_template_path(self, preferred_name: str) -> Path:
        folder = self._templates_dir(create=True)
        name = Path(preferred_name or "tpl.png").name
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            name = f"{name}.png"
        candidate = folder / name
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix or ".png"
        for i in range(2, 1000):
            alt = folder / f"{stem}_{i}{suffix}"
            if not alt.exists():
                return alt
        return folder / f"{stem}_{int(time.time())}{suffix}"

    def _import_image_bytes_to_templates(self, raw: bytes, preferred_name: str | None = None) -> dict:
        """Decode image bytes and save as PNG under data_dir/templates/."""
        import io

        from PIL import Image

        if not raw or len(raw) < 32:
            return {"ok": False, "error": "图片数据无效"}
        if len(raw) > 20 * 1024 * 1024:
            return {"ok": False, "error": "图片过大（超过 20MB）"}
        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in (img.mode or "") else "RGB")
        except Exception as exc:
            return {"ok": False, "error": f"无法解析图片: {exc}"}
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = Path(preferred_name or f"tpl_{stamp}.png").stem or f"tpl_{stamp}"
        out = self._unique_template_path(f"{base}.png")
        try:
            img.save(out, format="PNG")
        except Exception as exc:
            return {"ok": False, "error": f"保存失败: {exc}"}
        return {"ok": True, "path": str(out.resolve()), "name": out.name}

    def save_template_image(self, data_url: str, filename: str | None = None) -> dict:
        """Save a pasted/dropped image (data URL) into templates/ and return path."""
        import base64
        import re

        raw_url = str(data_url or "").strip()
        m = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", raw_url, re.DOTALL)
        if not m:
            return {"ok": False, "error": "无效的图片 data_url"}
        ext = m.group(1).lower().split("+")[0]
        if ext == "jpeg":
            ext = "jpg"
        try:
            blob = base64.b64decode(m.group(2), validate=False)
        except Exception as exc:
            return {"ok": False, "error": f"解码失败: {exc}"}
        preferred = None
        if isinstance(filename, str) and filename.strip():
            preferred = Path(filename.strip()).name
        elif ext in ("png", "jpg", "jpeg", "bmp", "webp", "gif"):
            preferred = f"tpl_{time.strftime('%Y%m%d_%H%M%S')}.{ext if ext != 'jpeg' else 'jpg'}"
        return self._import_image_bytes_to_templates(blob, preferred)

    def pick_template_image(self) -> dict:
        """Pick an image from disk; copy into templates/ and return the library path."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        start_dir = self._templates_dir(create=True)
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=str(start_dir),
            allow_multiple=False,
            file_types=(
                "Images (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif)",
                "All files (*.*)",
            ),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        src = result[0] if isinstance(result, (list, tuple)) else result
        src_path = Path(str(src)).expanduser()
        try:
            src_path = src_path.resolve()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not src_path.is_file():
            return {"ok": False, "error": "文件不存在"}
        # Already in templates library → reuse path as-is
        templates = self._templates_dir(create=False)
        if templates.is_dir() and self._is_under_dir(src_path, templates):
            return {"ok": True, "path": str(src_path), "name": src_path.name, "copied": False}
        try:
            raw = src_path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        saved = self._import_image_bytes_to_templates(raw, src_path.name)
        if not saved.get("ok"):
            return saved
        return {**saved, "copied": True, "source": str(src_path)}

    def export_text(self, text: str, filename: str | None = None) -> dict:
        """Save plain text via Save dialog (for logs export)."""
        raw = "" if text is None else str(text)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        suggested = (filename or f"nexuz-logs-{stamp}.txt").strip() or f"nexuz-logs-{stamp}.txt"
        if not suggested.lower().endswith(".txt"):
            suggested += ".txt"
        if not self._window:
            # Headless fallback: write next to exe/project
            out = exe_dir() / "logs" / Path(suggested).name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(raw, encoding="utf-8")
            return {"ok": True, "path": str(out)}
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(exe_dir()),
            save_filename=Path(suggested).name,
            file_types=("Text (*.txt)",),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        filepath = result if isinstance(result, str) else result[0]
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return {"ok": True, "path": str(path)}

    def get_run_log_info(self) -> dict:
        info = self._runtime_logs.info()
        return {"ok": True, "run_log": info}

    def export_run_log(self) -> dict:
        """Export the active/latest run log, already scoped to one flow and run."""
        exported = self._runtime_logs.export_text()
        if exported is None:
            return {"ok": False, "error": "当前没有可导出的流程运行日志"}
        text, info = exported
        flow_name = str(info.get("flow_name") or "未命名流程")
        run_id = str(info.get("run_id") or "run")
        stamp = time.strftime(
            "%Y%m%d_%H%M%S", time.localtime(float(info.get("started_at") or time.time()))
        )
        safe_flow = "".join(
            ch if ch not in '<>:"/\\|?*' else "_" for ch in flow_name
        ).strip(" ._") or "未命名流程"
        result = self.export_text(
            text, f"nexuz-{safe_flow[:48]}-{stamp}-{run_id}.txt"
        )
        if result.get("ok"):
            result["run_log"] = info
            result["count"] = int(info.get("record_count") or 0)
        return result

    def load_flow(self, filepath: str | None = None) -> dict:
        """Load a flow from the user data library by path."""
        if not filepath:
            return {"ok": False, "error": "请指定要打开的流程"}
        path = Path(str(filepath))
        flows = self._flows_dir(create=False)
        if not flows.is_dir() or not self._is_under_dir(path, flows):
            return {"ok": False, "error": "只能打开数据目录中的流程，请使用导入"}
        if not path.exists():
            return {"ok": False, "error": f"流程不存在: {path.name}"}
        data = json.loads(path.read_text(encoding="utf-8"))
        err = self._validate_flow(data)
        if err:
            return {"ok": False, "error": err, "path": str(path)}
        return {"ok": True, "flow": data, "path": str(path)}

    def pick_flow_file(self, library_only: bool = True) -> dict:
        """Pick a .flow.json file.

        library_only=True: must be under the user flows library (legacy).
        library_only=False: any local flow file; dialog starts in the library if present.
        """
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        flows = self._flows_dir(create=False)
        only_lib = bool(library_only)
        if only_lib and not flows.is_dir():
            return {"ok": False, "error": "数据目录中还没有流程，请先保存或导入"}
        start = str(flows) if flows.is_dir() else str(Path.home())
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=start,
            allow_multiple=False,
            file_types=("Flow JSON (*.flow.json;*.json)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        filepath = result[0] if isinstance(result, (list, tuple)) else result
        path = Path(str(filepath)).expanduser()
        try:
            path = path.resolve()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not path.is_file():
            return {"ok": False, "error": "文件不存在"}
        if only_lib and flows.is_dir() and not self._is_under_dir(path, flows):
            return {"ok": False, "error": "请选择数据目录中的流程"}
        return {"ok": True, "path": str(path)}

    def pick_local_path(self, mode: str = "open", suggested_name: str | None = None) -> dict:
        """Open Windows file dialog and return a local path (for file_io etc.).

        mode: ``open`` → existing file; ``save`` → save-as path (may not exist yet).
        """
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}
        kind = str(mode or "open").strip().lower()
        if kind not in ("open", "save"):
            kind = "open"
        start = str(Path.home())
        file_types = (
            "Text & data (*.txt;*.json;*.csv;*.log;*.md;*.xml;*.yaml;*.yml)",
            "All files (*.*)",
        )
        try:
            if kind == "save":
                name = (str(suggested_name or "").strip() or "untitled.txt")
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    directory=start,
                    save_filename=Path(name).name,
                    file_types=file_types,
                )
            else:
                result = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    directory=start,
                    allow_multiple=False,
                    file_types=file_types,
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not result:
            return {"ok": False, "cancelled": True}
        filepath = result if isinstance(result, str) else result[0]
        path = Path(str(filepath)).expanduser()
        try:
            path = path.resolve(strict=False)
        except Exception:
            pass
        return {"ok": True, "path": str(path), "mode": kind}

    def validate_flow(self, flow_json: str) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True}

    def _validate_flow(self, flow: dict) -> str | None:
        if not isinstance(flow, dict):
            return "FlowModel 必须是对象"
        if "nodes" not in flow or not isinstance(flow["nodes"], dict):
            return "缺少 nodes 字典"
        if "entry" not in flow:
            return "缺少 entry"
        if flow["entry"] and flow["entry"] not in flow["nodes"]:
            return f"entry 节点不存在: {flow['entry']}"
        if self._schema and Draft202012Validator:
            try:
                Draft202012Validator(self._schema).validate(flow)
            except Exception as exc:
                return str(exc)
        return None

    def _set_window_visible(self, visible: bool) -> None:
        if not self._window:
            return
        try:
            if visible:
                self._window.show()
            else:
                self._window.hide()
        except Exception:
            pass

    def _window_rect(self) -> dict[str, int] | None:
        hwnd = self._root_hwnd() or self._window_hwnd()
        if not hwnd:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            if not ctypes.windll.user32.GetWindowRect(
                ctypes.c_void_p(hwnd), ctypes.byref(rect)
            ):
                return None
            return {
                "left": int(rect.left),
                "top": int(rect.top),
                "width": max(1, int(rect.right - rect.left)),
                "height": max(1, int(rect.bottom - rect.top)),
            }
        except Exception:
            return None

    def _set_window_rect(self, left: int, top: int, width: int, height: int) -> bool:
        hwnd = self._root_hwnd() or self._window_hwnd()
        if not hwnd:
            return False
        try:
            import ctypes

            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            ok = ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(hwnd),
                None,
                int(left),
                int(top),
                max(1, int(width)),
                max(1, int(height)),
                SWP_NOZORDER | SWP_NOACTIVATE,
            )
            return bool(ok)
        except Exception:
            return False

    def _show_window_cmd(self, cmd: int) -> bool:
        """Win32 ShowWindow — safe from non-UI threads (unlike Form.WindowState)."""
        hwnd = self._root_hwnd() or self._window_hwnd()
        if not hwnd:
            return False
        try:
            import ctypes

            return bool(ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), int(cmd)))
        except Exception:
            return False

    def _work_area(self) -> dict[str, int]:
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            SPI_GETWORKAREA = 0x0030
            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            ):
                return {
                    "left": int(rect.left),
                    "top": int(rect.top),
                    "right": int(rect.right),
                    "bottom": int(rect.bottom),
                }
        except Exception:
            pass
        return {"left": 0, "top": 0, "right": 1920, "bottom": 1080}

    def _enter_run_monitor(self, flow: dict | None = None) -> None:
        """Shrink main WebView into a top-right run monitor (no Tk overlay, no hide)."""
        if self._run_monitor_active:
            self._run_monitor_flow = flow
            self._start_run_controls(flow=flow)
            return

        rect = self._window_rect()
        was_maximized = False
        try:
            was_maximized = bool(getattr(self, "_ui_maximized", False))
            state = getattr(self._window, "state", None) if self._window else None
            if state is not None and "maximized" in str(getattr(state, "name", state)).lower():
                was_maximized = True
        except Exception:
            pass

        prev_on_top = bool(getattr(self, "_ui_on_top", False))
        self._run_monitor_restore = {
            "rect": rect,
            "maximized": was_maximized,
            "on_top": prev_on_top,
            "min_w": 800,
            "min_h": 560,
        }
        self._run_monitor_flow = flow
        self._run_monitor_active = True
        self._run_hidden = False

        # Win32 only — never Form.WindowState / MinimumSize (deadlocks WebView2).
        SW_RESTORE = 9
        if was_maximized:
            self._show_window_cmd(SW_RESTORE)
            time.sleep(0.05)
            rect = self._window_rect() or rect
            if self._run_monitor_restore is not None:
                self._run_monitor_restore["rect"] = rect

        area = self._work_area()
        mon_w, mon_h = 360, 520
        margin = 24
        left = max(area["left"] + margin, area["right"] - mon_w - margin)
        top = area["top"] + margin
        self._set_window_rect(left, top, mon_w, mon_h)

        try:
            self._apply_window_topmost(True)
            self._ui_on_top = True
            self._sync_pywebview_on_top_flag(True)
        except Exception:
            pass

        self._start_run_controls(flow=flow)
        # Do not emit UI events here — App.tsx switches view from run_flow result.

    def _exit_run_monitor(self) -> None:
        """Restore window geometry / hotkeys. Does not drive frontend view."""
        was_active = bool(self._run_monitor_active) or self._run_monitor_restore is not None
        self._stop_run_controls()
        restore = self._run_monitor_restore
        self._run_monitor_active = False
        self._run_monitor_restore = None
        self._run_monitor_flow = None

        if not was_active:
            return

        def _restore() -> None:
            try:
                if not restore:
                    return
                rect = restore.get("rect") if isinstance(restore.get("rect"), dict) else None
                if rect:
                    self._set_window_rect(
                        int(rect.get("left") or 0),
                        int(rect.get("top") or 0),
                        int(rect.get("width") or 1400),
                        int(rect.get("height") or 900),
                    )
                if restore.get("maximized"):
                    SW_MAXIMIZE = 3
                    self._show_window_cmd(SW_MAXIMIZE)
                    self._ui_maximized = True
                want_top = bool(restore.get("on_top"))
                try:
                    self._apply_window_topmost(want_top)
                    self._ui_on_top = want_top
                    self._sync_pywebview_on_top_flag(want_top)
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True, name="nexuz-exit-monitor").start()

    # --- recording / capture providers ---
    def list_capture_providers(self) -> dict:
        return {"ok": True, "providers": get_provider_registry().list_providers()}

    def start_recording(
        self,
        min_interval_ms: int = 50,
        hide_window: bool = False,
        mode: str = "coord",
        coordinate_mode: str = "screen_abs",
    ) -> dict:
        """Start capture provider sequence recording."""
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        result = session.start(
            mode=mode or "coord",
            min_interval_ms=int(min_interval_ms),
            hide_window=bool(hide_window),
            coordinate_mode=coordinate_mode or "screen_abs",
        )
        if result.get("ok"):
            get_record_stop_hotkeys().start(on_stop=self._on_record_stop_hotkey)
        return result

    def stop_recording(self) -> dict:
        get_record_stop_hotkeys().stop()
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        if session.active:
            return session.stop()
        # Fallback: legacy recorder still running
        if get_recorder().recording:
            from backend.core.record_overlay import hide_stop_overlay

            hide_stop_overlay()
            nodes = get_recorder().stop()
            if getattr(self, "_recording_hidden", False):
                self._set_window_visible(True)
                self._recording_hidden = False
            return {"ok": True, "nodes": nodes, "mode": "coord"}
        return {"ok": False, "error_code": "NOT_RECORDING", "error": "当前未在录制", "nodes": []}

    def pick_click(
        self,
        mode: str = "coord",
        hide_window: bool = True,
        coordinate_mode: str = "screen_abs",
    ) -> dict:
        """Single click capture routed by mode (auto-detect mouse button)."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪", "error_code": "WINDOW_NOT_READY"}
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        return session.pick_click(
            mode=mode or "coord",
            hide_window=bool(hide_window),
            coordinate_mode=coordinate_mode or "screen_abs",
        )

    def list_windows(self) -> dict:
        """List visible top-level windows for the window-block picker."""
        from backend.core.window_coords import list_top_level_windows

        try:
            windows = list_top_level_windows()
            return {"ok": True, "windows": windows, "count": len(windows)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "windows": []}

    def pick_window(self, hide_window: bool = True) -> dict:
        """Click any window on screen; return title/process/class for window blocks."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪", "error_code": "WINDOW_NOT_READY"}

        import threading

        from pynput import mouse

        from backend.core.input.types import ERROR_CANCELLED, api_error, api_ok
        from backend.core.window_coords import capture_window_under_point

        result: dict | None = None
        done = threading.Event()

        def on_click(x, y, button, pressed):
            nonlocal result
            if not pressed:
                return True
            info = capture_window_under_point(int(x), int(y))
            if not info:
                result = api_error("PICK_FAILED", "未点到可用窗口，请点程序标题栏或客户区")
            else:
                result = api_ok(
                    title=info.get("title") or "",
                    process_name=info.get("process_name") or "",
                    class_name=info.get("class_name") or "",
                    pid=info.get("pid") or 0,
                    label=info.get("label") or "",
                    window=info,
                )
            done.set()
            return False

        do_hide = bool(hide_window)
        if do_hide:
            self._set_window_visible(False)
        listener = mouse.Listener(on_click=on_click)
        try:
            listener.start()
            finished = done.wait(timeout=120)
            try:
                listener.stop()
            except Exception:
                pass
            if not finished or result is None:
                return api_error(ERROR_CANCELLED, "已取消或超时", cancelled=True)
            return result
        finally:
            if do_hide:
                self._set_window_visible(True)

    # --- Frida session ---
    def frida_list_processes(self, options=None) -> dict:
        """
        Enumerate processes.
        pywebview 对多可选参数不稳定，统一收一个 options（dict 或兼容旧调用）。
        options: {query?, only_with_window?} 或直接传 query 字符串。
        """
        from backend.core.input.frida.session_manager import get_frida_session_manager

        query = None
        only_with_window = True
        if isinstance(options, dict):
            query = options.get("query")
            if "only_with_window" in options:
                only_with_window = bool(options.get("only_with_window"))
        elif isinstance(options, str):
            query = options
        elif options is None:
            pass
        else:
            only_with_window = bool(options)

        self._log("info", f"枚举进程…（仅有窗口={only_with_window}）")
        result = get_frida_session_manager().list_processes(
            query=query,
            only_with_window=only_with_window,
        )
        if result.get("ok"):
            self._log("ok", f"进程列表就绪：{result.get('count', 0)} 个")
        else:
            self._log("error", f"枚举进程失败：{result.get('error') or result.get('message')}")
        return result

    def frida_attach(self, options=None, pid=None) -> dict:
        """
        Attach by options dict {process_name|name, pid} or legacy (name, pid).
        """
        from backend.core.input.frida.session_manager import get_frida_session_manager

        process_name = None
        pid_i = None
        if isinstance(options, dict):
            process_name = options.get("process_name") or options.get("name")
            raw_pid = options.get("pid", pid)
        else:
            process_name = options
            raw_pid = pid
        if raw_pid is not None and str(raw_pid).strip() != "":
            try:
                pid_i = int(raw_pid)
            except Exception:
                pid_i = None

        self._log(
            "info",
            f"正在 Frida 连接：{process_name or '?'}{f' (PID {pid_i})' if pid_i else ''}",
        )
        result = get_frida_session_manager().attach(process_name=process_name, pid=pid_i)
        if result.get("ok") and result.get("attached") is not False:
            if result.get("hooked"):
                self._log(
                    "ok",
                    f"已连接 {result.get('process_name')} PID {result.get('pid')} · Hook 就绪",
                )
            else:
                warn = result.get("warning") or result.get("last_error") or "UI Hook 未就绪"
                self._log(
                    "warn",
                    f"已连接 {result.get('process_name')} PID {result.get('pid')}，但 Hook 未就绪：{warn}",
                )
        else:
            self._log(
                "error",
                f"Frida 连接失败：{result.get('error') or result.get('message') or '未知错误'}",
            )
        return result

    def frida_detach(self) -> dict:
        from backend.core.input.frida.session_manager import get_frida_session_manager

        self._log("info", "正在断开 Frida…")
        result = get_frida_session_manager().detach()
        self._log("ok", "Frida 已断开")
        return result

    def frida_status(self) -> dict:
        from backend.core.input.frida.session_manager import get_frida_session_manager

        return get_frida_session_manager().status()

    # --- screen pick ---
    def capture_desktop(self, hide_window: bool = True) -> dict:
        """Capture the full virtual desktop as a PNG data URL for screenshot picking."""
        import base64
        import io
        import time as _time

        from backend.blocks._helpers import grab_region, pack_coord_space
        from backend.core.dpi import virtual_screen_size

        do_hide = bool(hide_window) and bool(self._window)
        if do_hide:
            self._set_window_visible(False)
            # Let the hide settle so Nexuz is not in the shot
            _time.sleep(0.12)
        try:
            left, top, width, height = virtual_screen_size()
            if width <= 0 or height <= 0:
                return {"ok": False, "error": "无效的屏幕尺寸"}
            img = grab_region(left, top, left + width, top + height)
            buf = io.BytesIO()
            # Prefer lossless PNG so「截模板」裁切后还能和屏幕像素对齐；
            # JPEG 压缩会让后续图像匹配分数明显偏低。
            img.save(buf, format="PNG", optimize=True, compress_level=3)
            raw = buf.getvalue()
            mime = "image/png"
            if len(raw) > 40 * 1024 * 1024:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                raw = buf.getvalue()
                mime = "image/jpeg"
            data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            space = pack_coord_space()
            return {
                "ok": True,
                "data_url": data_url,
                "width": int(img.width),
                "height": int(img.height),
                "left": int(left),
                "top": int(top),
                "coord_space": space,
                "size": len(raw),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            if do_hide:
                self._set_window_visible(True)

    def pack_screen_point(self, x: int, y: int, color: str | None = None) -> dict:
        """Pack absolute screen point (+ optional color) like live pick_point."""
        try:
            from backend.blocks._helpers import pack_point, pixel_color, validate_point

            x, y = validate_point(int(x), int(y))
            packed = pack_point(x, y)
            if color and isinstance(color, str) and color.startswith("#"):
                packed["color"] = color.upper()
            else:
                try:
                    packed["color"] = pixel_color(x, y)
                except Exception:
                    packed["color"] = color
            return {"ok": True, **packed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pack_screen_region(self, region) -> dict:
        """Pack absolute screen region like live pick_region."""
        try:
            from backend.blocks._helpers import pack_region

            packed = pack_region(region)
            return {"ok": True, **packed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def capture_template_from_region(
        self,
        region,
        filename: str | None = None,
        data_url: str | None = None,
        left: int | None = None,
        top: int | None = None,
    ) -> dict:
        """Crop `region` and save as find-image template PNG.

        If `data_url` is provided (screenshot pick), crop from that image using
        virtual-desktop origin (`left`/`top`); otherwise grab the live desktop.
        """
        try:
            import base64
            import io
            import re

            from PIL import Image

            from backend.blocks._helpers import grab_region, pack_region, validate_region
            from backend.core.dpi import virtual_screen_size

            x1, y1, x2, y2 = validate_region(region)
            if isinstance(data_url, str) and data_url.startswith("data:"):
                m = re.match(r"^data:image/[^;]+;base64,(.+)$", data_url, re.DOTALL)
                if not m:
                    return {"ok": False, "error": "无效的截图 data_url"}
                raw = base64.b64decode(m.group(1))
                full = Image.open(io.BytesIO(raw)).convert("RGB")
                origin_left, origin_top, _, _ = virtual_screen_size()
                ox = int(left) if left is not None else int(origin_left)
                oy = int(top) if top is not None else int(origin_top)
                ix1 = max(0, x1 - ox)
                iy1 = max(0, y1 - oy)
                ix2 = min(full.width, x2 - ox)
                iy2 = min(full.height, y2 - oy)
                if ix2 <= ix1 or iy2 <= iy1:
                    return {"ok": False, "error": "裁切区域无效"}
                img = full.crop((ix1, iy1, ix2, iy2))
            else:
                img = grab_region(x1, y1, x2, y2)
            templates_dir = self._templates_dir(create=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = (
                filename.strip()
                if isinstance(filename, str) and filename.strip()
                else f"tpl_{stamp}.png"
            )
            if not name.lower().endswith(".png"):
                name += ".png"
            name = Path(name).name
            out = templates_dir / name
            img.save(out)
            packed = pack_region([x1, y1, x2, y2])
            return {
                "ok": True,
                "path": str(out),
                "region": packed["region"],
                "region_norm": packed.get("region_norm"),
                "coord_space": packed.get("coord_space"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def pick_point(
        self,
        hide_window: bool = True,
        coordinate_mode: str = "screen_abs",
    ) -> dict:
        """Compat alias → pick_click(coord); captures real mouse button."""
        result = self.pick_click(
            mode="coord",
            hide_window=hide_window,
            coordinate_mode=coordinate_mode or "screen_abs",
        )
        if not result.get("ok"):
            return result
        # Preserve legacy flat fields expected by Inspector applyPointPick
        params = result.get("params") or {}
        return {
            **result,
            "x": params.get("x", result.get("x")),
            "y": params.get("y", result.get("y")),
            "button": params.get("button", result.get("button")),
            "point_norm": params.get("point_norm", result.get("point_norm")),
            "coord_space": params.get("coord_space", result.get("coord_space")),
            "coordinate_mode": params.get("coordinate_mode", result.get("coordinate_mode")),
            "window_target": params.get("window_target", result.get("window_target")),
            "color": result.get("color"),
        }

    def pick_region(self, hide_window: bool = True) -> dict:
        """Fullscreen drag overlay to select a region (+ relative norm)."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}

        from backend.blocks._helpers import pack_region
        from backend.core.region_picker import pick_region_overlay

        do_hide = bool(hide_window)
        if do_hide:
            self._set_window_visible(False)
        try:
            picked = pick_region_overlay(timeout=120)
        finally:
            if do_hide:
                self._set_window_visible(True)
        if not picked.get("ok"):
            return picked
        packed = pack_region(picked["region"])
        return {"ok": True, **packed}

    def capture_template(self, hide_window: bool = True, filename: str | None = None) -> dict:
        """框选屏幕区域并保存为找图模板 PNG，返回路径。"""
        picked = self.pick_region(hide_window=hide_window)
        if not picked.get("ok"):
            return picked
        return self.capture_template_from_region(picked["region"], filename=filename)
