"""Local MCP bridge: token-authed 127.0.0.1 HTTP endpoint exposing Nexuz
blocks and flows to external AI agents (Claude Code / zcode via nexuz_mcp.py).

Security model:
- Binds 127.0.0.1 only; every app start generates a fresh random bearer token.
- The token is shared with local clients only via the port file
  (%LOCALAPPDATA%/Nexuz/mcp/port.json), same trust boundary as app config.
- run_block reuses the AI safety gates (allow_run_block / allow_dangerous);
  python_script / run_command / control-flow / user plugins stay hard-denied.
- run_flow goes through Api.run_flow with its full validation + execution
  policy chain — no bypass.
- Every mutating call is appended to the AI audit log.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from backend.paths import default_data_dir

_SERVER_NAME = "nexuz-mcp"
_MAX_BODY_BYTES = 32 * 1024 * 1024
_MAX_SHOTS = 8
_MAX_POINTS = 200

_state_lock = threading.Lock()
_state: dict[str, Any] = {"server": None, "thread": None, "token": None, "api": None}

# Cross-call context for run_block ({"context": dict, "counter": int}), same
# {node_id}.{output} convention as the interpreter / AI sessions.
_run_lock = threading.RLock()
_run_ctx: dict[str, Any] = {"context": {}, "counter": 0}
_artifacts: dict[str, Any] = {"shots": {}, "points": {}}


def port_file_path() -> Path:
    return default_data_dir() / "mcp" / "port.json"


def get_mcp_config() -> dict[str, Any]:
    from backend.paths import load_app_config

    raw = load_app_config().get("mcp")
    cfg = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "port": int(cfg.get("port") or 0),
    }


def set_mcp_config(patch: dict[str, Any]) -> dict[str, Any]:
    from backend.paths import load_app_config, save_app_config

    if not isinstance(patch, dict):
        patch = {}
    cfg = load_app_config()
    section = cfg.get("mcp") if isinstance(cfg.get("mcp"), dict) else {}
    if "enabled" in patch:
        section["enabled"] = bool(patch.get("enabled"))
    if patch.get("port") is not None:
        section["port"] = max(0, int(patch.get("port") or 0))
    cfg["mcp"] = section
    save_app_config(cfg)
    return {"enabled": bool(section.get("enabled", True)), "port": int(section.get("port") or 0)}


def _log_system(message: str, level: str = "info", detail: Any = None) -> None:
    try:
        from backend.core.log_hub import build_log_row, get_app_log_manager

        get_app_log_manager().write_row(
            build_log_row("mcp_bridge", {"message": message, "detail": detail}, message=message, level=level)
        )
    except Exception:
        pass


def _audit(event: dict[str, Any]) -> None:
    try:
        from backend.core.ai.audit import write_audit_event

        write_audit_event(event)
    except Exception:
        pass


def _prune_artifacts() -> None:
    shots = _artifacts["shots"]
    if len(shots) > _MAX_SHOTS:
        for sid in sorted(shots, key=lambda s: float(shots[s].get("created_at") or 0))[:-_MAX_SHOTS]:
            shots.pop(sid, None)
    points = _artifacts["points"]
    if len(points) > _MAX_POINTS:
        for pid in sorted(points)[: len(points) - _MAX_POINTS]:
            points.pop(pid, None)


def _resolve_flow_path(api: Any, flow_path: str) -> Path:
    flows = api._flows_dir(create=False)
    path = Path(str(flow_path)).expanduser()
    if not path.is_absolute():
        path = flows / path
    path = path.resolve()
    if not api._is_under_dir(path, flows):
        raise ValueError(f"flow_path 必须位于流程库内: {flows}")
    if path.suffix != ".json":
        raise ValueError("flow_path 必须是 .flow.json 文件")
    if not path.is_file():
        raise ValueError(f"流程文件不存在: {path}")
    return path


def dispatch(api: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    args = args if isinstance(args, dict) else {}

    if tool == "get_status":
        from backend.core.interpreter import get_interpreter

        cfg = _ai_cfg()
        return {
            "ok": True,
            "version": _version(),
            "pid": os.getpid(),
            "flow_running": bool(get_interpreter().running),
            "allow_run_block": bool(cfg.get("allow_run_block")),
            "allow_dangerous": bool(cfg.get("allow_dangerous")),
            "blocks_count": _blocks_count(),
        }

    if tool == "list_blocks":
        from backend.core.ai import tool_catalog

        return {
            "ok": True,
            "blocks": tool_catalog.list_blocks(
                category=args.get("category"),
                allow_dangerous=_ai_cfg().get("allow_dangerous", False),
            ),
        }

    if tool == "get_block_schema":
        from backend.core.ai import tool_catalog

        schema = tool_catalog.get_block_schema(
            str(args.get("type") or ""),
            allow_dangerous=_ai_cfg().get("allow_dangerous", False),
        )
        if schema is None:
            return {"ok": False, "error": f"未知积木: {args.get('type')}"}
        return {"ok": True, **schema}

    if tool == "list_flows":
        return api.list_flows()

    mutating = {"run_block", "run_flow", "flow_control", "capture_screen", "locate_text_on_screen", "reset_session"}
    if tool not in mutating:
        return {"ok": False, "error": f"未知工具: {tool}"}

    with _run_lock:
        if tool == "run_block":
            return _tool_run_block(args)
        if tool == "run_flow":
            return _tool_run_flow(api, args)
        if tool == "flow_control":
            return _tool_flow_control(api, args)
        if tool == "capture_screen":
            return _tool_capture_screen(api, args)
        if tool == "locate_text_on_screen":
            return _tool_locate_text(args)
        if tool == "reset_session":
            _run_ctx["context"] = {}
            _run_ctx["counter"] = 0
            return {"ok": True, "reset": True}
    return {"ok": False, "error": f"未知工具: {tool}"}


def _version() -> str:
    try:
        from backend.version import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _blocks_count() -> int:
    from backend.core.registry import BLOCK_REGISTRY

    return len(BLOCK_REGISTRY)


def _ai_cfg() -> dict[str, Any]:
    try:
        from backend.core.ai.config import get_ai_config

        cfg = get_ai_config()
        return {"allow_run_block": bool(cfg.allow_run_block), "allow_dangerous": bool(cfg.allow_dangerous)}
    except Exception:
        return {"allow_run_block": False, "allow_dangerous": False}


def _tool_run_block(args: dict[str, Any]) -> dict[str, Any]:
    from backend.core.ai.run_block import run_block_once

    cfg = _ai_cfg()
    result = run_block_once(
        {"type": args.get("type"), "params": args.get("params")},
        run_ctx=_run_ctx,
        allow_run_block=bool(cfg.get("allow_run_block")),
        allow_dangerous=bool(cfg.get("allow_dangerous")),
    )
    _audit(
        {
            "event": "mcp_run_block",
            "block_type": str(args.get("type") or ""),
            "ok": bool(result.get("ok")),
            "tier": result.get("tier"),
            "error": result.get("error"),
        }
    )
    return result


def _tool_run_flow(api: Any, args: dict[str, Any]) -> dict[str, Any]:
    flow: Any = None
    flow_label = ""
    if isinstance(args.get("flow"), dict):
        flow = args["flow"]
        flow_label = str(flow.get("name") or "inline")
    else:
        flow_path = str(args.get("flow_path") or "").strip()
        if not flow_path:
            return {"ok": False, "error": "run_flow 需要 flow_path 或 flow"}
        try:
            path = _resolve_flow_path(api, flow_path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            flow = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"流程文件读取失败: {exc}"}
        flow_label = str(path)

    wait = bool(args.get("wait", True))
    timeout_s = float(args.get("timeout_s") or 300)

    result = api.run_flow(flow, hide_window=bool(args.get("hide_window", True)))
    finished: dict[str, Any] | None = None
    if wait and result.get("ok"):
        from backend.core.interpreter import get_interpreter

        get_interpreter().wait_until_idle(timeout=timeout_s)
        finished = getattr(api, "_last_flow_finished", None)
        if not isinstance(finished, dict):
            finished = None

    _audit(
        {
            "event": "mcp_run_flow",
            "flow": flow_label[:200],
            "wait": wait,
            "ok": bool(result.get("ok")),
            "started": bool(result.get("started")),
            "blocked": bool(result.get("blocked")),
            "error": result.get("error"),
        }
    )
    return {"ok": True, "run": result, "finished": finished}


def _tool_flow_control(api: Any, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    fn: Callable[[], dict] | None = {
        "stop": api.stop_flow,
        "pause": api.pause_flow,
        "resume": api.resume_flow,
    }.get(action)
    if fn is None:
        return {"ok": False, "error": f"不支持的动作: {action}（stop/pause/resume）"}
    result = fn()
    _audit({"event": "mcp_flow_control", "action": action, "ok": bool(result.get("ok", True))})
    return result


def _tool_capture_screen(api: Any, args: dict[str, Any]) -> dict[str, Any]:
    from backend.core.ai.locate import capture_to_artifact

    cap = capture_to_artifact(api.capture_desktop, hide_window=bool(args.get("hide_window", True)))
    if not cap.get("ok"):
        return {"ok": False, "error": cap.get("error") or "截图失败"}
    art = cap["artifact"]
    _artifacts["shots"][art["shot_id"]] = art
    _prune_artifacts()
    return {
        "ok": True,
        "shot_ref": art["shot_id"],
        "width": art["width"],
        "height": art["height"],
        "left": art["left"],
        "top": art["top"],
        "coord_space": art["coord_space"],
        "data_url": art["data_url"],
    }


def _tool_locate_text(args: dict[str, Any]) -> dict[str, Any]:
    from backend.core.ai.locate import locate_text

    result = locate_text(
        _artifacts,
        match_text=str(args.get("match_text") or ""),
        match_mode=str(args.get("match_mode") or "contains"),
        shot_ref=args.get("shot_ref"),
        label=args.get("label"),
    )
    _audit(
        {
            "event": "mcp_locate_text",
            "match_text": str(args.get("match_text") or "")[:100],
            "ok": bool(result.get("ok")),
        }
    )
    return result


def _make_handler(token: str, api: Any) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._send_json(
                    200,
                    {"ok": True, "name": _SERVER_NAME, "version": _version(), "pid": os.getpid()},
                )
                return
            self._send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/rpc":
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            expected = f"Bearer {token}"
            got = str(self.headers.get("Authorization") or "")
            if not hmac.compare_digest(got, expected):
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_BODY_BYTES:
                self._send_json(413, {"ok": False, "error": "invalid body size"})
                return
            try:
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            tool = str((req or {}).get("tool") or "").strip()
            try:
                result = dispatch(api, tool, (req or {}).get("args"))
            except Exception as exc:
                _log_system(f"rpc dispatch failed: {tool}: {exc}", level="error")
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True, "result": result})

    return Handler


def start_mcp_bridge(api: Any) -> bool:
    """Start the local bridge if enabled. Returns whether it is listening."""
    with _state_lock:
        if _state["server"] is not None:
            return True
        cfg = get_mcp_config()
        if not cfg["enabled"]:
            _remove_port_file()
            return False
        token = secrets.token_urlsafe(32)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", cfg["port"]), _make_handler(token, api))
        except Exception as exc:
            _log_system(f"MCP bridge 启动失败: {exc}", level="error")
            return False
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True, name="nexuz-mcp-bridge"
        )
        thread.start()
        _state.update(server=server, thread=thread, token=token, api=api)
        _write_port_file(server.server_address[1], token)
        _log_system(f"MCP bridge listening on 127.0.0.1:{server.server_address[1]}")
        return True


def stop_mcp_bridge() -> None:
    with _state_lock:
        server = _state.get("server")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        _state.update(server=None, thread=None, token=None, api=None)
    _remove_port_file()
    _log_system("MCP bridge stopped")


def bridge_status() -> dict[str, Any]:
    with _state_lock:
        running = _state.get("server") is not None
        return {
            "running": running,
            "port": _state["server"].server_address[1] if running else None,
            "token": _state.get("token"),
            "pid": os.getpid() if running else None,
        }


def _write_port_file(port: int, token: str) -> None:
    try:
        path = port_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "name": _SERVER_NAME,
                    "port": int(port),
                    "token": token,
                    "pid": os.getpid(),
                    "version": _version(),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        _log_system(f"MCP port 文件写入失败: {exc}", level="error")


def _remove_port_file() -> None:
    try:
        port_file_path().unlink(missing_ok=True)
    except Exception:
        pass
