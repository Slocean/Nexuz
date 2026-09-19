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
import sys
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

# package.py 以 --add-data 打进冻结包的附属文件（壳进程脚本 + nexuz-mcp 技能），
# 运行时位于 sys._MEIPASS/nexuz_mcp_shell/ 下。
_BUNDLED_DIR = "nexuz_mcp_shell"

# 一键安装技能的目标目录（相对用户主目录）。
SKILL_INSTALL_DIRS = {
    "zcode": Path(".agents") / "skills" / "nexuz-mcp",
    "claude": Path(".claude") / "skills" / "nexuz-mcp",
}

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


def _bundle_root() -> Path | None:
    """冻结包内 nexuz_mcp_shell/ 目录；源码模式返回 None。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / _BUNDLED_DIR
    return None


def bundled_shell_path() -> Path | None:
    """包内内置的 nexuz_mcp.py（package.py --add-data），不存在返回 None。"""
    bundle = _bundle_root()
    if bundle is None:
        return None
    p = bundle / "nexuz_mcp.py"
    return p if p.is_file() else None


def bundled_skill_text() -> str | None:
    """nexuz-mcp 技能文本：打包版取内置副本，源码模式取仓库文件。"""
    candidates: list[Path] = []
    bundle = _bundle_root()
    if bundle is not None:
        candidates.append(bundle / "skills" / "nexuz-mcp" / "SKILL.md")
    from backend.paths import project_root

    candidates.append(project_root() / ".agents" / "skills" / "nexuz-mcp" / "SKILL.md")
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return None


def ensure_mcp_shell() -> tuple[Path, bool]:
    """确保壳进程脚本可用，返回 (路径, 是否存在)。

    源码模式直接用仓库根的 nexuz_mcp.py。打包版：exe 旁缺失或内容与内置
    副本不一致（热更新换 exe 后壳可能过时）时，从内置副本释放——优先 exe
    目录，不可写则退回数据目录 mcp/。
    """
    from backend.paths import exe_dir, project_root

    frozen = bool(getattr(sys, "frozen", False))
    shell = (exe_dir() if frozen else project_root()) / "nexuz_mcp.py"
    bundled = bundled_shell_path()
    if not frozen or bundled is None:
        return shell, shell.is_file()
    try:
        bundled_text = bundled.read_text(encoding="utf-8")
    except Exception:
        return shell, shell.is_file()
    try:
        if shell.is_file() and shell.read_text(encoding="utf-8") == bundled_text:
            return shell, True
    except Exception:
        pass
    for target in (exe_dir(), default_data_dir() / "mcp"):
        try:
            target.mkdir(parents=True, exist_ok=True)
            dest = target / "nexuz_mcp.py"
            dest.write_text(bundled_text, encoding="utf-8")
            if dest != shell:
                _log_system(f"MCP 壳进程脚本已释放到: {dest}")
            return dest, True
        except Exception:
            continue
    return shell, shell.is_file()


def install_skill_targets(
    clients: list[str] | None = None, *, home: Path | None = None
) -> dict[str, Any]:
    """把内置的 nexuz-mcp 技能写入用户主目录（覆盖旧副本，保持与应用同步）。"""
    text = bundled_skill_text()
    if text is None:
        return {"ok": False, "error": "未找到技能文件 SKILL.md（打包版应内置 nexuz_mcp_shell/skills/）"}
    base = home or Path.home()
    chosen = {k: v for k, v in SKILL_INSTALL_DIRS.items() if not clients or k in clients}
    if not chosen:
        return {"ok": False, "error": f"未知客户端: {clients}（支持 zcode / claude）"}
    results: dict[str, Any] = {}
    for name, rel in chosen.items():
        dest = base / rel / "SKILL.md"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            results[name] = {"ok": True, "path": str(dest)}
        except Exception as exc:
            results[name] = {"ok": False, "path": str(dest), "error": str(exc)}
    return {"ok": all(r["ok"] for r in results.values()), "results": results}


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


def _tool_recent_runs(limit: int = 20) -> dict[str, Any]:
    """最近运行状况：当前运行会话 + 定时任务失败记录尾部（只读，供控制台/agent）。"""
    from backend.core.runtime_log import get_runtime_log_manager
    from backend.core.scheduler import _failures_file

    try:
        limit = min(max(int(limit), 1), 100)
    except (TypeError, ValueError):
        limit = 20
    failures: list[dict[str, Any]] = []
    path = _failures_file()
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    failures.append(json.loads(line))
                except Exception:
                    continue
        except OSError:
            pass
    current: dict[str, Any] | None = None
    try:
        info = get_runtime_log_manager().info()
        if isinstance(info, dict):
            current = info
    except Exception:
        pass
    return {"ok": True, "current_run": current, "failures": failures}


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


def dispatch(
    api: Any,
    tool: str,
    args: dict[str, Any],
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = args if isinstance(args, dict) else {}

    if tool == "get_status":
        from backend.core.host_mode import is_headless
        from backend.core.interpreter import get_interpreter

        cfg = _ai_cfg()
        out = {
            "ok": True,
            "version": _version(),
            "pid": os.getpid(),
            "headless": is_headless(),
            "flow_running": bool(get_interpreter().running),
            "allow_run_block": bool(cfg.get("allow_run_block")),
            "allow_dangerous": bool(cfg.get("allow_dangerous")),
            "blocks_count": _blocks_count(),
        }
        # 浏览器会话摘要（alive/engine/url/title/tabs）：廉价探测，绝不拉起浏览器
        try:
            from backend.core.browser.session import session_status

            out["browser"] = session_status()
        except Exception:
            pass
        return out

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

    if tool == "list_schedules":
        from backend.core.scheduler import get_scheduler

        sched = get_scheduler()
        return {"ok": True, "available": sched.available, "jobs": sched.list_jobs()}

    if tool == "recent_runs":
        return _tool_recent_runs()

    known = {"run_block", "run_flow", "flow_control", "capture_screen", "locate_text_on_screen", "reset_session"}
    if tool not in known:
        return {"ok": False, "error": f"未知工具: {tool}"}

    # 无头服务器：屏幕类工具明确报错，避免 agent 反复重试（ServerApi 的
    # capture_desktop 也会拒绝，此处先行短路给出统一文案）。
    if tool in {"capture_screen", "locate_text_on_screen"}:
        from backend.core.host_mode import is_headless

        if is_headless():
            return {"ok": False, "error": f"服务器形态无屏幕：{tool} 不可用"}

    if tool == "flow_control":
        # 独立锁：run_flow(wait=True) 挂死时 stop 必须仍可达
        with _control_lock:
            return _tool_flow_control(api, args)

    with _run_lock:
        if tool == "run_block":
            return _tool_run_block(args, identity)
        if tool == "run_flow":
            return _tool_run_flow(api, args, identity)
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


def _tool_run_block(
    args: dict[str, Any], identity: dict[str, Any] | None = None
) -> dict[str, Any]:
    from backend.core.ai.run_block import run_block_once
    from backend.core import api_keys

    btype = str((args or {}).get("type") or "").strip()
    if identity is not None and not api_keys.block_allowed(identity, btype):
        return {"ok": False, "error": f"该密钥的积木白名单不包含: {btype}"}
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


def _tool_run_flow(
    api: Any,
    args: dict[str, Any],
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    node_types = sorted(
        {
            str(node.get("type") or "")
            for node in (flow.get("nodes") or {}).values()
            if isinstance(node, dict)
        }
        - {""}
    )
    # API Key 积木白名单：静态拒绝越界类型；allow_only 随 floor 进解释器，
    # call_subflow 加载的子流程同样被逐节点强制（管道类积木豁免）。
    if identity is not None:
        from backend.core import api_keys

        disallowed = api_keys.flow_allowlist_floor(identity, set(node_types))
        if disallowed:
            return {
                "ok": False,
                "blocked": True,
                "error": "流程包含该密钥积木白名单之外的积木: " + ", ".join(disallowed),
            }
        allowlist = api_keys.identity_allowlist(identity)
        if allowlist:
            floor = {**floor, "allow_only": allowlist}
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


# Web 前端桥接（POST /api/<method>）暴露的方法白名单：只含 ServerApi 上的
# 无头安全方法；桌面交互类（pick_*/window_*/recording/frida/capture 等）
# 一律不在列，浏览器端走 mockCall 或得到 ok:false。
SERVER_API_METHODS = frozenset(
    {
        "ping",
        "get_app_info",
        "get_resource_stats",
        "get_data_dir_info",
        "get_block_registry",
        "get_user_blocks_dir",
        "list_user_block_files",
        "list_flows",
        "load_flow",
        "save_flow",
        "delete_flow",
        "rename_flow",
        "duplicate_flow",
        "run_flow",
        "pause_flow",
        "resume_flow",
        "continue_flow",
        "stop_flow",
        "force_reset",
        "is_running",
        "validate_flow",
        "set_breakpoints",
        "step_flow",
        "drain_ui_events",
        "list_schedule_jobs",
        "remove_schedule_job",
        "get_run_log_info",
        "export_run_log",
        "get_ui_settings",
        "set_ui_settings",
        "get_hotkeys",
        "set_hotkeys",
        "set_diag_logging",
        "get_diag_logging",
        "get_notice_read_id",
        "set_notice_read_id",
        "mcp_get_status",
        "browser_status",
        "ai_get_config",
        "log_audit",
        "log_system",
        "fetch_announcement",
        "fetch_notice",
        "check_for_update",
        "read_local_image",
        "capture_desktop",
        "run_block",
        "apikey_list",
        "apikey_create",
        "apikey_update",
        "apikey_delete",
    }
)

_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}


def _dist_dir() -> Path:
    """服务器托管的前端产物：优先 dist-server（build:server 产物），
    回退 dist（桌面构建产物，开发期兜底）。"""
    from backend.paths import project_root

    frontend = project_root() / "frontend"
    server_dist = frontend / "dist-server"
    if server_dist.is_dir():
        return server_dist
    return frontend / "dist"


def _serve_static(handler: Any, rel: str) -> bool:
    """无头模式托管 frontend/dist（SPA：未命中的路径回退 index.html）。"""
    try:
        root = _dist_dir().resolve()
    except Exception:
        return False
    if not root.is_dir():
        return False
    target = root / rel if rel else root / "index.html"
    try:
        resolved = target.resolve()
    except Exception:
        return False
    if resolved != root and root not in resolved.parents:
        return False
    if not resolved.is_file():
        resolved = root / "index.html"
        if not resolved.is_file():
            return False
    try:
        body = resolved.read_bytes()
    except OSError:
        return False
    mime = _STATIC_MIME.get(resolved.suffix.lower(), "application/octet-stream")
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header(
        "Cache-Control", "no-cache" if resolved.name == "index.html" else "max-age=3600"
    )
    handler.end_headers()
    handler.wfile.write(body)
    return True


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
            path = self.path.split("?")[0].strip("/")
            if path == "health":
                self._send_json(
                    200,
                    {"ok": True, "name": _SERVER_NAME, "version": _version(), "pid": os.getpid()},
                )
                return
            # 无头服务器：GET 一律尝试托管前端静态资源（frontend/dist，SPA 回退
            # index.html）。桌面模式保持 404 不变。
            from backend.core.host_mode import is_headless

            if is_headless() and _serve_static(self, path):
                return
            self._send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?")[0].rstrip("/")
            if path == "/rpc":
                self._handle_rpc()
                return
            if path.startswith("/api/"):
                self._handle_api()
                return
            self._send_json(404, {"ok": False, "error": "not found"})

        def _read_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_BODY_BYTES:
                self._send_json(413, {"ok": False, "error": "invalid body size"})
                return None
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return None

        def _identity(self) -> tuple[str | None, dict[str, Any] | None]:
            """解析请求凭证。返回 (bearer, identity)：
            - 未携带/无效（含 API Key 校验失败或已停用）→ (None, None)（调用方回 401）；
            - 主密钥 → (bearer, None)（全权）；
            - API Key → (bearer, 该记录)（按 scopes / block_allowlist 授权）。"""
            got = str(self.headers.get("Authorization") or "")
            if not got.startswith("Bearer "):
                return None, None
            bearer = got[len("Bearer "):].strip()
            if not bearer:
                return None, None
            if hmac.compare_digest(bearer, token):
                return bearer, None
            from backend.core import api_keys

            record = api_keys.authenticate(bearer)
            if record is None:
                return None, None
            return bearer, record

        def _handle_api(self) -> None:
            """Web 前端桥接：POST /api/<method>，body {"args": [...]}。

            主密钥全权；API Key 按 scopes 判定（apikey_* 管理方法仅主密钥），
            积木白名单对 run_block / run_flow 额外强制。
            """
            from backend.core import api_keys
            from backend.core.host_mode import is_headless

            bearer, identity = self._identity()
            if bearer is None:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            if not is_headless():
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            method = self.path.split("?")[0].rstrip("/")[len("/api/"):].strip("/")
            if method not in SERVER_API_METHODS:
                self._send_json(404, {"ok": False, "error": f"服务器不提供方法: {method}"})
                return
            if not api_keys.method_allowed(identity, method):
                required = api_keys.METHOD_SCOPES.get(method)
                hint = f"（需要能力: {required}）" if required else "（仅主密钥）"
                self._send_json(403, {"ok": False, "error": f"无权调用 {method}{hint}"})
                return
            fn = getattr(api, method, None)
            if not callable(fn):
                self._send_json(404, {"ok": False, "error": f"服务器不提供方法: {method}"})
                return
            body = self._read_body()
            if body is None:
                return
            args = body.get("args") if isinstance(body, dict) else None
            args = args if isinstance(args, list) else []

            # 积木白名单（API Key 可选配置）：单积木直查；流程按节点类型集合判
            if identity is not None and method in ("run_block", "run_flow"):
                spec = args[0] if args and isinstance(args[0], dict) else None
                if method == "run_block":
                    if not api_keys.block_allowed(identity, (spec or {}).get("type")):
                        self._send_json(
                            403,
                            {
                                "ok": False,
                                "error": (
                                    "该密钥的积木白名单不包含: "
                                    f"{(spec or {}).get('type')}"
                                ),
                            },
                        )
                        return
                elif spec is not None:
                    nodes = spec.get("nodes")
                    types = {
                        str(n.get("type") or "")
                        for n in nodes.values()
                        if isinstance(nodes, dict) and isinstance(n, dict)
                    }
                    types.discard("")
                    disallowed = api_keys.flow_allowlist_floor(identity, types)
                    if disallowed:
                        self._send_json(
                            403,
                            {
                                "ok": False,
                                "error": "流程包含该密钥积木白名单之外的积木: "
                                + ", ".join(disallowed),
                            },
                        )
                        return

            if not _rpc_slots.acquire(timeout=2.0):
                self._send_json(503, {"ok": False, "error": "busy: too many concurrent rpc"})
                return
            try:
                result = fn(*args)
                self._send_json(200, {"ok": True, "result": result})
            except Exception as exc:
                _log_system(f"api call failed: {method}: {exc}", level="error")
                self._send_json(500, {"ok": False, "error": str(exc)})
            finally:
                _rpc_slots.release()

        def _handle_rpc(self) -> None:
            from backend.core import api_keys

            bearer, identity = self._identity()
            if bearer is None:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            req = self._read_body()
            if req is None:
                return
            tool = str((req or {}).get("tool") or "").strip()
            if not api_keys.tool_allowed(identity, tool):
                required = api_keys.TOOL_SCOPES.get(tool)
                hint = f"（需要能力: {required}）" if required else "（仅主密钥）"
                self._send_json(403, {"ok": False, "error": f"无权调用 {tool}{hint}"})
                return
            args = (req or {}).get("args")
            if identity is not None and tool == "run_block" and isinstance(args, dict):
                if not api_keys.block_allowed(identity, args.get("type")):
                    self._send_json(
                        403,
                        {
                            "ok": False,
                            "error": f"该密钥的积木白名单不包含: {args.get('type')}",
                        },
                    )
                    return
            # 并发上限：超过 _MAX_CONCURRENT_RPC 个在途 RPC 直接拒绝（503）
            if not _rpc_slots.acquire(timeout=2.0):
                self._send_json(503, {"ok": False, "error": "busy: too many concurrent rpc"})
                return
            try:
                result = dispatch(api, tool, args, identity=identity)
            except Exception as exc:
                _log_system(f"rpc dispatch failed: {tool}: {exc}", level="error")
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            finally:
                _rpc_slots.release()
            self._send_json(200, {"ok": True, "result": result})

    return Handler


def start_mcp_bridge(
    api: Any,
    *,
    host: str | None = None,
    port: int | None = None,
    token: str | None = None,
) -> bool:
    """Start the local bridge if enabled. Returns whether it is listening.

    host/port/token 供无头服务器入口（backend/server.py）显式指定；
    桌面版零参调用走原有路径：尊重 [mcp].enabled，127.0.0.1 + 随机 token。
    """
    with _state_lock:
        if _state["server"] is not None:
            return True
        cfg = get_mcp_config()
        explicit = any(v is not None for v in (host, port, token))
        if not explicit and not cfg["enabled"]:
            _remove_port_file()
            return False
        bind_host = host or "127.0.0.1"
        bind_port = int(port) if port else int(cfg["port"] or 0)
        use_token = token or secrets.token_urlsafe(32)
        try:
            server = ThreadingHTTPServer((bind_host, bind_port), _make_handler(use_token, api))
        except Exception as exc:
            _log_system(f"MCP bridge 启动失败: {exc}", level="error")
            return False
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True, name="nexuz-mcp-bridge"
        )
        thread.start()
        _state.update(server=server, thread=thread, token=use_token, api=api)
        _write_port_file(server.server_address[1], use_token)
        _log_system(f"MCP bridge listening on {bind_host}:{server.server_address[1]}")
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
