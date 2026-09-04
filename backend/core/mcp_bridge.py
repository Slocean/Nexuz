"""Local MCP bridge: token-authed 127.0.0.1 HTTP endpoint exposing Nexuz
blocks and flows to external AI agents (Claude Code / zcode via nexuz_mcp.py).

Security model:
- Binds 127.0.0.1 only; every app start generates a fresh random bearer token.
- The token is shared with local clients only via the port file
  (%LOCALAPPDATA%/Nexuz/mcp/port.json), same trust boundary as app config.
- Authorization for external agents lives at the connecting AI client (tool
  approval) + audit log; the in-app AI switches (allow_run_block /
  allow_dangerous) do NOT gate MCP calls.
- Hard-deny regardless of switches or flow content: python_script /
  run_command / user plugins / power_action (run_block tier lists; run_flow
  via the __policy_floor__ marker enforced per-node, incl. subflows and
  scheduled re-fires); control-flow blocks are interpreter-only.
- run_flow keeps the flow's own execution policy (safe-mode elevated blocks
  stay blocked) — the floor can only tighten, never loosen.
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
# _run_lock serializes mutating work (run_block/run_flow/...). flow_control
# uses a SEPARATE lock: when run_flow(wait=True) holds _run_lock on a hung
# flow, stop/pause must still get through — that is the whole point of 止损.
_run_lock = threading.RLock()
_control_lock = threading.RLock()
_run_ctx: dict[str, Any] = {"context": {}, "counter": 0}
_artifacts: dict[str, Any] = {"shots": {}, "points": {}}

# Bound concurrent RPC dispatch (each slot holds a worker thread for the whole
# call — run_flow(wait=True) can occupy one for minutes).
_MAX_CONCURRENT_RPC = 8
_rpc_slots = threading.BoundedSemaphore(_MAX_CONCURRENT_RPC)


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
        from backend.core.execution_policy import CRITICAL_TYPES

        blocks = tool_catalog.list_blocks(
            category=args.get("category"),
            allow_dangerous=True,
        )
        # 危险命令类不可由外部 AI 执行，不进入目录，避免 agent 无效尝试
        return {
            "ok": True,
            "blocks": [b for b in blocks if str(b.get("type") or "") not in CRITICAL_TYPES],
        }

    if tool == "get_block_schema":
        from backend.core.ai import tool_catalog
        from backend.core.execution_policy import CRITICAL_TYPES

        btype = str(args.get("type") or "")
        if btype in CRITICAL_TYPES:
            return {"ok": False, "error": f"积木 {btype} 不可由外部 AI 执行"}
        schema = tool_catalog.get_block_schema(btype, allow_dangerous=True)
        if schema is None:
            return {"ok": False, "error": f"未知积木: {args.get('type')}"}
        return {"ok": True, **schema}

    if tool == "list_flows":
        return api.list_flows()

    known = {"run_block", "run_flow", "flow_control", "capture_screen", "locate_text_on_screen", "reset_session"}
    if tool not in known:
        return {"ok": False, "error": f"未知工具: {tool}"}

    if tool == "flow_control":
        # 独立锁：run_flow(wait=True) 挂死时 stop 必须仍可达
        with _control_lock:
            return _tool_flow_control(api, args)

    with _run_lock:
        if tool == "run_block":
            return _tool_run_block(args)
        if tool == "run_flow":
            return _tool_run_flow(api, args)
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

    # 外部 AI 的授权由所接入的 AI 客户端（工具审批）负责，不受应用内 AI 开关
    # 约束；硬拒清单（危险命令类 / 控制流 / 用户插件 / 电源操作）在
    # run_block_once 内保持不变，无开关可绕。
    result = run_block_once(
        {"type": args.get("type"), "params": args.get("params")},
        run_ctx=_run_ctx,
        allow_run_block=True,
        allow_dangerous=True,
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

    # 外部 AI 下限闸：危险命令类 / 自定义积木 / 电源操作一律拒绝（双保险）——
    # ① 此处静态预扫，对顶层节点给出即时明确的报错；
    # ② __policy_floor__ 随流程字典进入解释器逐节点强制（覆盖 call_subflow
    #    嵌套加载的子流程，杜绝"外层干净、内层藏 python_script"的绕行），
    #    并由定时任务在每次触发时重新注入（杜绝注册后改写流程文件的绕行）。
    # 流程自带的 execution_policy 仍然生效（safe 模式的 elevated 拦截等），
    # 但无法削弱下限。其余正常积木全部放行，不再要求应用内开关。
    from backend.core.execution_policy import (
        apply_policy_floor,
        mcp_policy_floor,
        resolve_execution_policy,
        scan_flow_violations,
    )

    floor = mcp_policy_floor()
    policy = apply_policy_floor(resolve_execution_policy(flow), floor)
    violations = scan_flow_violations(flow, policy)
    if violations:
        labels = "、".join(
            f"{item['block_type']}（{item['node_id']}）" for item in violations[:5]
        )
        return {
            "ok": False,
            "error": f"外部 AI 不可执行含危险命令类积木的流程：{labels}",
            "blocked": True,
            "policy": policy.to_dict(),
            "violations": violations,
        }

    flow = {**flow, "__run_origin__": "mcp", "__policy_floor__": floor}
    node_types = sorted(
        {
            str(node.get("type") or "")
            for node in (flow.get("nodes") or {}).values()
            if isinstance(node, dict)
        }
        - {""}
    )

    wait = bool(args.get("wait", True))
    timeout_s = float(args.get("timeout_s") or 300)

    result = api.run_flow(flow, hide_window=bool(args.get("hide_window", True)))
    finished: dict[str, Any] | None = None
    timed_out = False
    if wait and result.get("ok"):
        from backend.core.interpreter import get_interpreter

        interp = get_interpreter()
        interp.wait_until_idle(timeout=timeout_s)
        finished = getattr(api, "_last_flow_finished", None)
        if not isinstance(finished, dict):
            finished = None
        # wait_until_idle 无返回值：超时后流程仍在跑即为 timed_out
        timed_out = bool(getattr(interp, "running", False))

    _audit(
        {
            "event": "mcp_run_flow",
            "flow": flow_label[:200],
            "blocks": node_types,
            "policy": policy.to_dict(),
            "wait": wait,
            "ok": bool(result.get("ok")),
            "started": bool(result.get("started")),
            "blocked": bool(result.get("blocked")),
            "timed_out": timed_out,
            "error": result.get("error"),
        }
    )
    return {"ok": True, "run": result, "finished": finished, "timed_out": timed_out}


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
        # 死连接看门狗：socket 读写级超时（非请求总时长），只杀无响应的对端
        timeout = 30

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
            # 并发上限：超过 _MAX_CONCURRENT_RPC 个在途 RPC 直接拒绝（503）
            if not _rpc_slots.acquire(timeout=2.0):
                self._send_json(503, {"ok": False, "error": "busy: too many concurrent rpc"})
                return
            try:
                result = dispatch(api, tool, (req or {}).get("args"))
            except Exception as exc:
                _log_system(f"rpc dispatch failed: {tool}: {exc}", level="error")
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            finally:
                _rpc_slots.release()
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
