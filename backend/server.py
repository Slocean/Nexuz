"""Nexuz 无头服务器入口 — 同一引擎（interpreter/registry/scheduler/mcp_bridge），
无 GUI 宿主，可在 Windows / Linux (WSL Ubuntu) 上作为常驻服务部署。

桌面版入口是 backend/main.py（pywebview）；本文件是它的服务器孪生：

- HTTP 接口（带 token）：
    POST /rpc            —— MCP 工具协议（run_block / run_flow / list_flows / …）
    POST /api/<method>   —— Web 前端桥接（frontend/src/bridge.js 在无 pywebview
                            环境下走这里，白名单见 mcp_bridge.SERVER_API_METHODS）
    GET  /               —— 托管 frontend/dist 构建产物（前端界面）
    GET  /health         —— 探活
- 流程库即目录：data_dir/flows 下放 .flow.json（git pull / scp 同步部署）。
- 定时任务经 schedule_trigger 注册，jobs.json 持久化，跨重启自动恢复；
  通知（触发/失败/流程结束）经 NotifySink 外发 webhook 或写日志。
- 无头口径（docs/headless_server.md）：requires="desktop" 的积木在 run_block
  与 run_flow 两条路径均被拒绝；Linux 上无需任何桌面依赖。

用法：

    python backend/server.py                       # 127.0.0.1 + 自动端口
    python backend/server.py --host 0.0.0.0 --port 9800
    python backend/server.py --data-dir /srv/nexuz --token-file /etc/nexuz/token
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

# Bootstrap project root onto sys.path before importing backend.*
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOGO = r"""
_   _ ______ _   _ _____  _____ _____  ______ _____  _  _______ _____ _   _
| \ | |  ____| \ | |  __ \|_   _|  __ \|  ____|  __ \| |/ / ____|_   _| \ | |
|  \| | |__  |  \| | |  | | | | | |  | |  __| | |__) | ' /|  __| | | |  \| |
| . ` |  __| | . ` | |  | | | | | |  | | |_  |  _  /|  < | |_    | | | . ` |
| |\  | |____| |\  | |__| |_| |_| |__| | |____| | \ \| . \|____|_| |_| |\  |
|_| \_|______|_| \_|_____/|_____|_____/|______|_|  \_\_|\_\_____|_____|_| \_|
                              headless server
"""

# 浏览器模式下前端 UI 设置的默认值（与 bridge.js 的 _browserUiSettings 对齐）
_UI_DEFAULTS = {
    "hideWindowOnRecord": False,
    "showToolbarLabels": True,
    "nodeContextMenuMode": "grouped",
    "hideSidePanelsOnSettings": True,
    "autoSaveEnabled": False,
    "autoSaveIntervalSec": 60,
    "saveAfterRun": True,
    "defaultCaptureMode": "coord",
    "defaultPickMethod": "screenshot",
    "defaultCoordinateMode": "window_client",
    "defaultOutputCoordinateMode": "window_client",
    "defaultNodeIntervalMs": 500,
    "themeName": "Ocean",
    "themeMode": "dark",
    "diagLogging": False,
    "autoCheckUpdate": True,
    "aiMode": "chat",
}
_HOTKEY_DEFAULTS = {
    "start_run": ["x", "f3"],
    "stop_run": ["x", "f4"],
    "pause_run": ["x", "f5"],
    "record_stop": ["x", "f10"],
    "plugin_mode": ["x", "f6"],
    "click_through": ["x", "f7"],
}


class ServerApi:
    """无头门面：实现 Web 前端（bridge.js）与 MCP 工具层触达的方法子集。

    刻意不 import backend.api（其顶层 import webview 依赖 GUI 绑定）；
    运行链复用 backend.core.flow_runner，与桌面版同一条代码路径。
    方法白名单见 mcp_bridge.SERVER_API_METHODS。
    """

    def __init__(self, emit: Callable[[str, dict], None] | None = None):
        from backend.core.flow_runner import load_flow_schema

        self._user_emit = emit or (lambda event, payload: None)
        self._schema = load_flow_schema()
        self._last_flow_finished: dict[str, Any] | None = None
        self._event_lock = threading.Lock()
        self._event_queue: deque[dict[str, Any]] = deque(maxlen=5000)
        self._started_at = time.time()
        self._ui_settings: dict[str, Any] = {**_UI_DEFAULTS}
        self._ui_settings_persisted = False
        self._hotkeys: dict[str, Any] = {**_HOTKEY_DEFAULTS}
        self._notice_read_id = ""

    # --- 事件通路：interpreter/scheduler emit → 队列（前端 drain）+ 通知汇 ---

    def _emit(self, event: str, payload: dict) -> None:
        payload = payload if isinstance(payload, dict) else {}
        if event == "flow_finished":
            self._last_flow_finished = payload
            try:
                from backend.core.runtime_log import get_runtime_log_manager

                log_info = get_runtime_log_manager().finish(payload)
                if log_info:
                    payload = {**payload, "run_log": log_info}
            except Exception:
                pass
            try:
                from backend.core.scheduler import get_scheduler

                get_scheduler().on_flow_finished()
            except Exception:
                pass
        with self._event_lock:
            self._event_queue.append({"event": event, "payload": payload})
        self._user_emit(event, payload)

    # --- 基础信息 ---

    def ping(self) -> dict:
        return {"ok": True, "message": "pong (nexuz-server)", "dpi_scale": 1.0}

    def get_app_info(self) -> dict:
        from backend.version import GITHUB_OWNER, GITHUB_REPO, RELEASES_PAGE_URL, __version__

        return {
            "ok": True,
            "version": __version__,
            "frozen": False,
            "headless": True,
            "github": f"{GITHUB_OWNER}/{GITHUB_REPO}",
            "releases_url": RELEASES_PAGE_URL,
        }

    def get_resource_stats(self) -> dict:
        try:
            import psutil

            proc = psutil.Process()
            vm = psutil.virtual_memory()
            return {
                "ok": True,
                "pid": os.getpid(),
                "cpu_percent": proc.cpu_percent(interval=None),
                "rss_bytes": proc.memory_info().rss,
                "threads": proc.num_threads(),
                "uptime_s": int(time.time() - self._started_at),
                "system_cpu_percent": psutil.cpu_percent(interval=None),
                "system_mem_percent": vm.percent,
                "system_mem_total_bytes": vm.total,
                "system_mem_used_bytes": vm.total - vm.available,
                "ui_queue": len(self._event_queue),
                "exec_running": bool(self.is_running().get("running")),
                "ts": time.time(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_data_dir_info(self) -> dict:
        from backend.paths import default_data_dir, get_data_dir, load_app_config

        root = get_data_dir(create=False)
        default = default_data_dir()
        return {
            "ok": True,
            "path": str(root),
            "exists": root.is_dir(),
            "default_path": str(default),
            "is_default": root.resolve() == default.resolve(),
        }

    # --- 积木注册表（无头过滤：真机积木不进前端面板） ---

    def get_block_registry(self) -> list[dict]:
        from backend.core.host_mode import is_headless
        from backend.core.registry import get_schemas, register_all_blocks

        register_all_blocks()
        schemas = get_schemas()
        if is_headless():
            schemas = [s for s in schemas if str(s.get("requires") or "") != "desktop"]
        return schemas

    def get_user_blocks_dir(self) -> dict:
        from backend.core.registry import get_user_blocks_dir

        try:
            return {"ok": True, "path": str(get_user_blocks_dir()), "exists": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": ""}

    def list_user_block_files(self) -> dict:
        out = self.get_user_blocks_dir()
        files: list[dict] = []
        root = Path(out.get("path") or "")
        if out.get("ok") and root.is_dir():
            for p in sorted(root.glob("*.py")):
                if p.name.startswith("_"):
                    continue
                files.append({"name": p.name, "path": str(p), "trusted": True, "sha256": ""})
        return {"ok": True, "path": out.get("path", ""), "files": files}

    # --- 流程库（目录即库） ---

    def list_flows(self) -> dict:
        from backend.paths import get_data_dir

        folder = get_data_dir(create=False) / "flows"
        if not folder.is_dir():
            return {"ok": True, "flows": [], "dir": str(folder), "exists": False}
        items = []
        for path in sorted(
            folder.glob("*.flow.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
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

    def load_flow(self, filepath: str | None = None) -> dict:
        from backend.core.flow_runner import validate_flow
        from backend.paths import get_data_dir

        if not filepath:
            return {"ok": False, "error": "请指定要打开的流程"}
        path = Path(str(filepath))
        flows = get_data_dir(create=False) / "flows"
        if not self._is_under_dir(path, flows):
            return {"ok": False, "error": "只能打开数据目录中的流程"}
        if not path.is_file():
            return {"ok": False, "error": f"流程不存在: {path.name}"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"流程文件读取失败: {exc}"}
        err = validate_flow(data, self._schema)
        if err:
            return {"ok": False, "error": err, "path": str(path)}
        return {"ok": True, "flow": data, "path": str(path)}

    def save_flow(self, flow_json: str, filepath: str | None = None, name: str | None = None) -> dict:
        """保存到流程库（镜像 Api.save_flow 语义：路径必须落在 flows 目录内）。"""
        from backend.paths import get_data_dir

        flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        if not isinstance(flow, dict):
            return {"ok": False, "error": "无效的流程对象"}
        if name and str(name).strip():
            flow = {**flow, "name": str(name).strip()}

        flows = get_data_dir(create=True) / "flows"
        if filepath:
            path = Path(str(filepath))
            if not self._is_under_dir(path, flows):
                flow_name = str(flow.get("name") or name or "").strip() or "未命名流程"
                path = flows / f"{_safe_stem(flow_name)}.flow.json"
        else:
            flow_name = str(flow.get("name") or name or "").strip()
            if not flow_name:
                return {"ok": False, "error": "请先为流程命名"}
            path = flows / f"{_safe_stem(flow_name)}.flow.json"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": flow.get("name")}

    def delete_flow(self, filepath: str) -> dict:
        from backend.paths import get_data_dir

        path = Path(str(filepath))
        flows = get_data_dir(create=False) / "flows"
        if not flows.is_dir() or not self._is_under_dir(path, flows):
            return {"ok": False, "error": "只能删除数据目录内的流程"}
        if not path.is_file():
            return {"ok": False, "error": f"流程不存在: {path.name}"}
        path.unlink()
        return {"ok": True, "path": str(path)}

    def rename_flow(self, filepath: str, new_name: str) -> dict:
        new_name = str(new_name or "").strip()
        if not new_name:
            return {"ok": False, "error": "新名称不能为空"}
        loaded = self.load_flow(filepath)
        if not loaded.get("ok"):
            return loaded
        path = Path(str(loaded["path"]))
        flow = {**loaded["flow"], "name": new_name}
        path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path), "name": new_name}

    def duplicate_flow(self, filepath: str, new_name: str | None = None) -> dict:
        loaded = self.load_flow(filepath)
        if not loaded.get("ok"):
            return loaded
        flow = dict(loaded["flow"])
        base = str(new_name or "").strip() or f"{flow.get('name') or 'flow'} 副本"
        name = base
        target = self._unique_flow_path(flow.get("name") or base, suffix_hint=name)
        flow["name"] = name if new_name else (flow.get("name") or base)
        target.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(target), "name": flow.get("name")}

    def _unique_flow_path(self, display_name: str, suffix_hint: str = "") -> Path:
        from backend.paths import get_data_dir

        flows = get_data_dir(create=True) / "flows"
        stem = _safe_stem(suffix_hint or display_name)
        candidate = flows / f"{stem}.flow.json"
        i = 2
        while candidate.exists():
            candidate = flows / f"{stem} ({i}).flow.json"
            i += 1
        return candidate

    # --- 运行控制 ---

    def run_flow(
        self,
        flow_json: str,
        step_mode: bool = False,
        hide_window: bool = True,
        debug_mode: bool = False,
        breakpoints=None,
    ) -> dict:
        from backend.core.flow_runner import prepare_flow, start_flow

        flow, err, issues = prepare_flow(flow_json, schema=self._schema)
        if err:
            if issues is not None:
                return {
                    "ok": False,
                    "error": err,
                    "blocked": True,
                    "validation_issues": issues,
                }
            return {"ok": False, "error": err}
        try:
            out = start_flow(
                flow,
                emit=self._emit,
                step_mode=step_mode,
                debug_mode=debug_mode,
                breakpoints=breakpoints,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "started": out.get("started", True),
            "resumed": out.get("resumed", False),
            "hide_window": False,
            "run_log": out.get("run_log"),
        }

    def pause_flow(self) -> dict:
        from backend.core.interpreter import get_interpreter

        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.pause()
        return {"ok": True, "paused": True}

    def resume_flow(self) -> dict:
        from backend.core.interpreter import get_interpreter

        interp = get_interpreter()
        if not interp.running:
            return {"ok": False, "error": "当前没有运行中的流程"}
        interp.resume()
        return {"ok": True, "resumed": True}

    def continue_flow(self) -> dict:
        return self.resume_flow()

    def stop_flow(self) -> dict:
        from backend.core.interpreter import get_interpreter

        get_interpreter().stop()
        return {"ok": True, "stopping": True}

    def force_reset(self) -> dict:
        from backend.core.interpreter import get_interpreter

        get_interpreter(emit=self._emit).force_reset()
        return {"ok": True, "cleared": ["flow"]}

    def is_running(self) -> dict:
        from backend.core.interpreter import get_interpreter

        interp = get_interpreter()
        return {
            "ok": True,
            "running": bool(interp.running),
            "paused": bool(getattr(interp, "paused", False)),
            "at_breakpoint": bool(getattr(interp, "at_breakpoint", False)),
            "debug_mode": bool(getattr(interp, "debug_mode", False)),
        }

    def validate_flow(self, flow_json: str) -> dict:
        from backend.core.flow_runner import validate_flow

        try:
            flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        err = validate_flow(flow, self._schema)
        return {"ok": err is None, "error": err} if err else {"ok": True}

    def set_breakpoints(self, node_ids=None) -> dict:
        return {"ok": True}

    def step_flow(self) -> dict:
        return {"ok": False, "error": "服务器模式不支持单步调试"}

    def drain_ui_events(self) -> dict:
        with self._event_lock:
            messages = list(self._event_queue)
            self._event_queue.clear()
        return {"ok": True, "messages": messages}

    # --- 定时任务 ---

    def list_schedule_jobs(self) -> dict:
        from backend.core.scheduler import get_scheduler

        sched = get_scheduler()
        return {"ok": True, "available": sched.available, "jobs": sched.list_jobs()}

    def remove_schedule_job(self, job_id: str) -> dict:
        from backend.core.scheduler import get_scheduler

        get_scheduler().remove_job(str(job_id))
        return {"ok": True}

    # --- 运行日志 ---

    def get_run_log_info(self) -> dict:
        from backend.core.runtime_log import get_runtime_log_manager

        return {"ok": True, "run_log": get_runtime_log_manager().info()}

    def export_run_log(self) -> dict:
        from backend.core.runtime_log import get_runtime_log_manager

        exported = get_runtime_log_manager().export_text()
        if not exported:
            return {"ok": False, "error": "暂无运行日志"}
        text, info = exported
        return {"ok": True, "text": text, "info": info}

    # --- UI 设置 / 快捷键 / 通知（内存态；服务器无窗口，仅保 UI 一致性） ---

    def get_ui_settings(self) -> dict:
        return {"ok": True, "settings": {**self._ui_settings}, "persisted": self._ui_settings_persisted}

    def set_ui_settings(self, patch=None) -> dict:
        patch = patch if isinstance(patch, dict) else {}
        self._ui_settings.update(patch)
        self._ui_settings_persisted = True
        return {"ok": True, "settings": {**self._ui_settings}, "persisted": True}

    def get_hotkeys(self) -> dict:
        return self._hotkeys_payload()

    def set_hotkeys(self, prefs=None) -> dict:
        prefs = prefs if isinstance(prefs, dict) else {}
        for slot, keys in _HOTKEY_DEFAULTS.items():
            if isinstance(prefs.get(slot), list):
                self._hotkeys[slot] = prefs[slot]
        return self._hotkeys_payload()

    def _hotkeys_payload(self) -> dict:
        def label(keys: list) -> str:
            return "+".join(str(k).upper() for k in keys or [])

        labels = {k: label(v) for k, v in self._hotkeys.items()}
        return {
            "ok": True,
            **self._hotkeys,
            **{f"{k}_label": v for k, v in labels.items()},
            "hotkeys": {**self._hotkeys},
            "labels": labels,
            "defaults": {**_HOTKEY_DEFAULTS},
        }

    def set_diag_logging(self, enabled: bool = False) -> dict:
        self._ui_settings["diagLogging"] = bool(enabled)
        return {"ok": True, "enabled": bool(enabled)}

    def get_diag_logging(self) -> dict:
        return {"ok": True, "enabled": bool(self._ui_settings.get("diagLogging"))}

    def get_notice_read_id(self) -> dict:
        return {"ok": True, "id": self._notice_read_id}

    def set_notice_read_id(self, notice_id: str | None = None) -> dict:
        self._notice_read_id = str(notice_id or "")
        return {"ok": True, "id": self._notice_read_id}

    # --- 只读外设状态 / 降级接口 ---

    def mcp_get_status(self) -> dict:
        from backend.core.mcp_bridge import bridge_status, get_mcp_config
        from backend.version import __version__

        cfg = get_mcp_config()
        status = bridge_status()
        return {
            "ok": True,
            "enabled": True,
            "configured_port": int(cfg["port"] or 0),
            "running": bool(status["running"]),
            "listen_port": status["port"],
            "token": None,
            "pid": status["pid"],
            "port_file": "",
            "version": __version__,
        }

    def browser_status(self) -> dict:
        try:
            from backend.core.browser.session import session_status

            out = session_status()
            return {
                "ok": True,
                "config": {"engine": "auto", "headless": True, "keep_alive": False},
                "running": bool(out.get("alive")),
                "engine": out.get("engine"),
                "browser_found": True,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ai_get_config(self) -> dict:
        try:
            from backend.core.ai.config import get_ai_config

            cfg = get_ai_config()
            data = cfg.to_dict() if hasattr(cfg, "to_dict") else dict(vars(cfg))
            data.setdefault("has_api_key", bool(data.get("api_key_masked")))
            data.setdefault("options", {})
            data.setdefault("presets", [])
            return {"ok": True, "config": data}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def log_audit(self, message: str = "", detail=None) -> dict:
        return {"ok": True}

    def log_system(self, message: str = "", level: str = "info", detail=None) -> dict:
        return {"ok": True}

    def fetch_announcement(self) -> dict:
        return {"ok": False, "error": "服务器模式不支持在线公告"}

    def fetch_notice(self) -> dict:
        return {"ok": False, "error": "服务器模式不支持在线通知"}

    def check_for_update(self) -> dict:
        from backend.version import __version__

        return {
            "ok": True,
            "update_available": False,
            "current_version": __version__,
            "latest_version": __version__,
            "message": "服务器模式不检查更新",
        }

    def read_local_image(self, filepath: str | None = None) -> dict:
        import base64
        import mimetypes

        from backend.paths import get_data_dir

        path = Path(str(filepath or ""))
        root = get_data_dir(create=False)
        if not self._is_under_dir(path, root):
            return {"ok": False, "error": "只能读取数据目录内的图片"}
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在: {path.name}"}
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"ok": True, "data_url": f"data:{mime};base64,{data}"}

    # --- mcp_bridge 依赖的目录辅助 ---

    def _flows_dir(self, *, create: bool = False) -> Path:
        from backend.paths import get_data_dir

        d = get_data_dir(create=create) / "flows"
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

    # --- 无头明确拒绝的桌面方法（ServerApi 未列入白名单的兜底示例） ---

    def capture_desktop(self, hide_window: bool = True) -> dict:
        return {"ok": False, "error": "服务器形态无屏幕：capture_desktop 不可用"}


def _safe_stem(name: str) -> str:
    cleaned = "".join(ch for ch in str(name or "flow") if ch not in '\\/:*?"<>|').strip()
    return cleaned[:80] or "flow"


def _resolve_token(token_file: str) -> str:
    """--token-file > 数据目录持久化 token（常驻进程重启不变）。"""
    if token_file.strip():
        text = Path(token_file.strip()).read_text(encoding="utf-8").strip()
        if not text:
            raise SystemExit(f"token 文件为空: {token_file}")
        return text.splitlines()[0].strip()
    from backend.paths import get_data_dir

    token_path = get_data_dir(create=True) / "mcp" / "token"
    try:
        existing = token_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexuz headless server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=0, help="监听端口（默认自动分配）")
    parser.add_argument("--data-dir", default="", help="数据根目录（默认 %LOCALAPPDATA%\\Nexuz）")
    parser.add_argument("--token-file", default="", help="鉴权 token 文件（默认持久化到数据目录）")
    parser.add_argument("--webhook-url", default="", help="通知 webhook（默认读 config.json [server].webhook_url）")
    args = parser.parse_args()

    if args.data_dir.strip():
        os.environ["NEXUZ_DATA_DIR"] = str(Path(args.data_dir.strip()).expanduser())

    from backend.core import host_mode
    from backend.core.mcp_bridge import bridge_status, start_mcp_bridge
    from backend.core.notify_sink import NotifySink
    from backend.core.registry import register_all_blocks
    from backend.core.scheduler import get_scheduler

    host_mode.set_headless(True)
    register_all_blocks()

    sink = NotifySink(webhook_url=args.webhook_url or None)
    api = ServerApi(emit=sink.emit)

    sched = get_scheduler()
    sched.set_emit(sink.emit)
    try:
        restored = sched.restore_from_disk()
    except Exception as exc:
        restored = 0
        print(f"[server] 恢复定时任务失败: {exc}", file=sys.stderr, flush=True)

    try:
        token = _resolve_token(args.token_file)
    except OSError as exc:
        print(f"[server] token 读取失败: {exc}", file=sys.stderr, flush=True)
        return 1

    if not start_mcp_bridge(api, host=args.host, port=args.port, token=token):
        print("[server] MCP bridge 启动失败", file=sys.stderr, flush=True)
        return 1
    status = bridge_status()
    print(_LOGO)
    print(f"[server] Nexuz headless listening on {args.host}:{status['port']}")
    print(f"[server] 控制台: http://{'127.0.0.1' if args.host == '127.0.0.1' else '<服务器IP>'}:{status['port']}/")
    print(f"[server] data_dir: {os.environ.get('NEXUZ_DATA_DIR') or '(default)'}")
    print(f"[server] 定时任务已恢复: {restored}")
    print("[server] token:", status.get("token"))
    if args.host != "127.0.0.1":
        print("[server] 警告：监听地址不是 127.0.0.1，请确保前置 HTTPS 反代与强 token", file=sys.stderr, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[server] bye", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
