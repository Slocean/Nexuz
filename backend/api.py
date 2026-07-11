"""pywebview JS-Bridge API."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import webview

from backend.core.dpi import get_dpi_scale, screen_size_logical
from backend.core.interpreter import get_interpreter
from backend.core.recorder import get_recorder
from backend.core.registry import get_schemas, register_all_blocks

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
        get_recorder().set_stop_hotkey_callback(self._on_record_stop_hotkey)

    def _on_record_stop_hotkey(self) -> None:
        if not get_recorder().recording:
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

    def _load_flow_schema(self) -> dict | None:
        path = Path(__file__).resolve().parent.parent / "schemas" / "flow_schema.json"
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

    # --- flow execution ---
    def run_flow(self, flow_json: str, step_mode: bool = False, hide_window: bool = True) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        err = self._validate_flow(flow)
        if err:
            return {"ok": False, "error": err}
        interp = get_interpreter(emit=self._emit)
        # Hide during continuous run so pyautogui clicks cannot land on Nexuz sidebar/buttons.
        # Keep visible in step mode so the user can press Step / Pause.
        do_hide = bool(hide_window) and not bool(step_mode)
        self._run_hidden = do_hide
        if do_hide:
            self._set_window_visible(False)
            time.sleep(0.15)
        try:
            interp.run_flow(flow, step_mode=bool(step_mode))
            return {"ok": True, "started": True, "hide_window": do_hide}
        except Exception as exc:
            if do_hide:
                self._set_window_visible(True)
                self._run_hidden = False
            return {"ok": False, "error": str(exc)}

    def pause_flow(self) -> dict:
        get_interpreter().pause()
        return {"ok": True}

    def resume_flow(self) -> dict:
        get_interpreter().resume()
        return {"ok": True}

    def stop_flow(self) -> dict:
        get_interpreter().stop()
        if self._run_hidden:
            self._set_window_visible(True)
            self._run_hidden = False
        return {"ok": True}

    def step_flow(self) -> dict:
        get_interpreter().step()
        return {"ok": True}

    def is_running(self) -> dict:
        return {"running": get_interpreter().running}

    # --- file ---
    def save_flow(self, flow_json: str, filepath: str | None = None) -> dict:
        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if not filepath:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory="",
                save_filename=f"{flow.get('name', 'flow')}.flow.json",
                file_types=("Flow JSON (*.flow.json;*.json)",),
            ) if self._window else None
            if not result:
                return {"ok": False, "cancelled": True}
            filepath = result if isinstance(result, str) else result[0]
        path = Path(filepath)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path)}

    def load_flow(self, filepath: str | None = None) -> dict:
        if not filepath:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Flow JSON (*.flow.json;*.json)",),
            ) if self._window else None
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

    # --- recording ---
    def start_recording(self, min_interval_ms: int = 50, hide_window: bool = True) -> dict:
        rec = get_recorder()
        rec.min_interval_ms = int(min_interval_ms)
        self._recording_hidden = bool(hide_window)
        if self._recording_hidden:
            self._set_window_visible(False)
        rec.start()
        return {"ok": True, "hide_window": self._recording_hidden}

    def stop_recording(self) -> dict:
        nodes = get_recorder().stop()
        if getattr(self, "_recording_hidden", False):
            self._set_window_visible(True)
            self._recording_hidden = False
        return {"ok": True, "nodes": nodes}

    # --- screen pick ---
    def pick_point(self, hide_window: bool = True) -> dict:
        """One left-click on screen to pick a point (not a region overlay)."""
        if not self._window:
            return {"ok": False, "error": "窗口未就绪"}

        from backend.blocks._helpers import pack_point, pixel_color

        self._pick_result = None
        self._pick_event.clear()
        do_hide = bool(hide_window)
        if do_hide:
            self._set_window_visible(False)

        def listen():
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if pressed and button == mouse.Button.left:
                    try:
                        color = pixel_color(int(x), int(y))
                    except Exception:
                        color = None
                    packed = pack_point(int(x), int(y))
                    self._pick_result = {
                        "ok": True,
                        "x": packed["x"],
                        "y": packed["y"],
                        "color": color,
                        "point_norm": packed["point_norm"],
                        "coord_space": packed["coord_space"],
                    }
                    self._pick_event.set()
                    return False
                return True

            with mouse.Listener(on_click=on_click) as listener:
                listener.join()

        threading.Thread(target=listen, daemon=True).start()
        self._pick_event.wait(timeout=120)
        if do_hide:
            self._set_window_visible(True)
        return self._pick_result or {"ok": False, "cancelled": True}

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
            templates_dir = Path(__file__).resolve().parent.parent / "templates"
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
