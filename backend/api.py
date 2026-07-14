"""pywebview JS-Bridge API."""

from __future__ import annotations

import json
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
from backend.core.registry import get_schemas, register_all_blocks
from backend.paths import exe_dir, project_root

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

    def _on_record_stop_hotkey(self) -> None:
        session = get_recording_session()
        if not session.active and not get_recorder().recording:
            return
        result = self.stop_recording()
        self._emit("recording_stopped", result)

    def _emit(self, event: str, payload: dict) -> None:
        if not self._window:
            return
        try:
            data = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
            self._window.evaluate_js(f"window.__nexuzEmit && window.__nexuzEmit({data})")
        except Exception:
            pass
        # After run ends, show window again (was hidden so OS clicks wouldn't hit Nexuz UI)
        if event in ("flow_finished", "flow_stopped") and self._run_hidden:
            self._set_window_visible(True)
            self._run_hidden = False

    def _log(self, level: str, message: str, **detail) -> None:
        payload: dict[str, Any] = {"level": level, "message": message}
        if detail:
            payload["detail"] = detail
        self._emit("log", payload)

    def _load_flow_schema(self) -> dict | None:
        path = project_root() / "schemas" / "flow_schema.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # --- basic ---
    def ping(self) -> dict:
        return {"ok": True, "message": "pong", "dpi_scale": get_dpi_scale()}

    def get_block_registry(self) -> list[dict]:
        # Re-scan so newly added blocks appear without restarting the process
        register_all_blocks()
        return get_schemas()

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


    # --- flow execution ---
    def run_flow(self, flow_json: str, step_mode: bool = False, hide_window: bool = True) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        interp = get_interpreter(emit=self._emit)

        # If a session is already paused, resume it — do not hide / restart.
        if interp.running and getattr(interp, "paused", False):
            try:
                result = interp.run_flow(flow, step_mode=bool(step_mode))
                return {"ok": True, "resumed": True, **(result or {})}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # Hide during continuous run so pyautogui clicks cannot land on Nexuz sidebar/buttons.
        # Keep visible in step mode so the user can press Step / Pause.
        do_hide = bool(hide_window) and not bool(step_mode)
        self._run_hidden = do_hide
        if do_hide:
            self._set_window_visible(False)
            time.sleep(0.15)
        try:
            result = interp.run_flow(flow, step_mode=bool(step_mode))
            return {
                "ok": True,
                "started": bool((result or {}).get("started", True)),
                "resumed": bool((result or {}).get("resumed")),
                "hide_window": do_hide,
            }
        except Exception as exc:
            if do_hide:
                self._set_window_visible(True)
                self._run_hidden = False
            return {"ok": False, "error": str(exc)}

    def pause_flow(self) -> dict:
        """Pause execution and show window so user can Continue / Stop."""
        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.pause()
        if self._run_hidden:
            self._set_window_visible(True)
            # Keep flag so stop/finish still restore cleanly; window stays visible for controls.
            self._run_hidden = False
        return {"ok": True, "paused": True}

    def resume_flow(self) -> dict:
        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.resume()
        return {"ok": True, "resumed": True}

    def stop_flow(self) -> dict:
        get_interpreter().stop()
        self._set_window_visible(True)
        self._run_hidden = False
        return {"ok": True, "stopping": True}

    def step_flow(self) -> dict:
        get_interpreter().step()
        return {"ok": True}

    def is_running(self) -> dict:
        interp = get_interpreter()
        return {
            "running": interp.running,
            "paused": bool(getattr(interp, "paused", False)),
        }

    # --- file / flow library ---
    def _flows_dir(self) -> Path:
        # Writable next to exe when frozen; project root in dev.
        d = exe_dir() / "flows"
        d.mkdir(parents=True, exist_ok=True)
        return d

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

    def list_flows(self) -> dict:
        """List flows saved under project /flows directory."""
        items = []
        folder = self._flows_dir()
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
        return {"ok": True, "flows": items, "dir": str(folder)}

    def delete_flow(self, filepath: str) -> dict:
        path = Path(str(filepath))
        flows = self._flows_dir().resolve()
        try:
            resolved = path.resolve()
            if flows not in resolved.parents and resolved.parent != flows:
                return {"ok": False, "error": "只能删除 flows 目录内的流程"}
            if not resolved.is_file():
                return {"ok": False, "error": "文件不存在"}
            resolved.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # --- flow templates library (流程模板，不同于截图 templates/) ---
    def _flow_templates_dir(self) -> Path:
        d = exe_dir() / "flow_templates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_flow_templates(self) -> dict:
        """List user-saved flow templates under /flow_templates."""
        items = []
        folder = self._flow_templates_dir()
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
        path = self._flow_templates_dir() / self._safe_flow_filename(tpl_name)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": tpl_name}

    def delete_flow_template(self, filepath: str) -> dict:
        path = Path(str(filepath))
        folder = self._flow_templates_dir().resolve()
        try:
            resolved = path.resolve()
            if folder not in resolved.parents and resolved.parent != folder:
                return {"ok": False, "error": "只能删除 flow_templates 目录内的模板"}
            if not resolved.is_file():
                return {"ok": False, "error": "文件不存在"}
            resolved.unlink()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def load_flow_template(self, filepath: str) -> dict:
        """Load a flow template by path (must be under flow_templates/)."""
        path = Path(str(filepath))
        folder = self._flow_templates_dir().resolve()
        try:
            resolved = path.resolve()
            if folder not in resolved.parents and resolved.parent != folder:
                return {"ok": False, "error": "只能加载 flow_templates 目录内的模板"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return self.load_flow(str(path))

    def save_flow(self, flow_json: str, filepath: str | None = None, name: str | None = None) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if name and str(name).strip():
            flow = {**flow, "name": str(name).strip()}

        if not filepath:
            # Prefer library save when a name is provided
            if name and str(name).strip():
                filepath = str(self._flows_dir() / self._safe_flow_filename(str(name).strip()))
            else:
                result = (
                    self._window.create_file_dialog(
                        webview.SAVE_DIALOG,
                        directory=str(self._flows_dir()),
                        save_filename=self._safe_flow_filename(flow.get("name") or "flow"),
                        file_types=("Flow JSON (*.flow.json;*.json)",),
                    )
                    if self._window
                    else None
                )
                if not result:
                    return {"ok": False, "cancelled": True}
                filepath = result if isinstance(result, str) else result[0]

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": flow.get("name")}

    def clipboard_write(self, text: str) -> dict:
        """Copy text to system clipboard (pywebview often blocks navigator.clipboard)."""
        raw = "" if text is None else str(text)
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(raw)
            root.update()
            root.destroy()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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

    def load_flow(self, filepath: str | None = None) -> dict:
        if not filepath:
            result = (
                self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    directory=str(self._flows_dir()),
                    allow_multiple=False,
                    file_types=("Flow JSON (*.flow.json;*.json)",),
                )
                if self._window
                else None
            )
            if not result:
                return {"ok": False, "cancelled": True}
            filepath = result[0] if isinstance(result, (list, tuple)) else result
        path = Path(filepath)
        if not path.exists():
            return {"ok": False, "error": f"文件不存在: {filepath}"}
        data = json.loads(path.read_text(encoding="utf-8"))
        err = self._validate_flow(data)
        if err:
            return {"ok": False, "error": err, "path": str(path)}
        return {"ok": True, "flow": data, "path": str(path)}

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

    # --- recording / capture providers ---
    def list_capture_providers(self) -> dict:
        return {"ok": True, "providers": get_provider_registry().list_providers()}

    def start_recording(
        self,
        min_interval_ms: int = 50,
        hide_window: bool = False,
        mode: str = "coord",
    ) -> dict:
        """Start capture provider sequence recording."""
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        return session.start(
            mode=mode or "coord",
            min_interval_ms=int(min_interval_ms),
            hide_window=bool(hide_window),
        )

    def stop_recording(self) -> dict:
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

    def pick_click(self, mode: str = "coord", hide_window: bool = True) -> dict:
        """Single click capture routed by mode (auto-detect mouse button)."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪", "error_code": "WINDOW_NOT_READY"}
        session = get_recording_session(
            set_window_visible=self._set_window_visible,
            emit=self._emit,
        )
        return session.pick_click(mode=mode or "coord", hide_window=bool(hide_window))

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
    def pick_point(self, hide_window: bool = True) -> dict:
        """Compat alias → pick_click(coord); captures real mouse button."""
        result = self.pick_click(mode="coord", hide_window=hide_window)
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
        region = picked["region"]
        try:
            from backend.blocks._helpers import grab_region, validate_region

            x1, y1, x2, y2 = validate_region(region)
            img = grab_region(x1, y1, x2, y2)
            templates_dir = exe_dir() / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = filename.strip() if isinstance(filename, str) and filename.strip() else f"tpl_{stamp}.png"
            if not name.lower().endswith(".png"):
                name += ".png"
            # sanitize basename
            name = Path(name).name
            out = templates_dir / name
            img.save(out)
            return {
                "ok": True,
                "path": str(out),
                "region": region,
                "region_norm": picked.get("region_norm"),
                "coord_space": picked.get("coord_space"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
