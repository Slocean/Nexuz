"""Nexuz MCP stdio shell — bridges MCP clients (Claude Code / zcode) to the
Nexuz desktop app over a local token-authed HTTP endpoint.

Stdlib only. Protocol traffic goes to stdout; diagnostics go to stderr.

Client config (source checkout):
    claude mcp add nexuz -- python E:\\Project\\Nexuz\\nexuz_mcp.py

Packaged app: set NEXUZ_EXE to the installed Nexuz.exe so the shell can
wake the app when it is not running:
    claude mcp add nexuz --env NEXUZ_EXE=C:\\...\\Nexuz.exe -- python nexuz_mcp.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVER_NAME = "nexuz"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_VERSION = "2024-11-05"
WAKE_TIMEOUT_S = 40.0
DEFAULT_CALL_TIMEOUT_S = 120.0

TOOLS = [
    {
        "name": "get_status",
        "description": "获取 Nexuz 状态：版本、是否正在执行流程、应用内 AI 开关（allow_run_block/allow_dangerous，仅约束应用内 AI，对外部 AI 调用不生效）、浏览器会话摘要（browser: 开没开/引擎/当前页 URL/页签数）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_blocks",
        "description": "按分类列出可用积木（type/label/简述）。编排或执行前先调用以了解平台能力。",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "可选分类过滤：动作类/识别类/系统类等"}},
        },
    },
    {
        "name": "get_block_schema",
        "description": "获取单个积木的完整 inputs 定义与 outputs，再据此填写 run_block 的 params。",
        "inputSchema": {
            "type": "object",
            "properties": {"type": {"type": "string", "description": "积木 type，如 click、screenshot"}},
            "required": ["type"],
        },
    },
    {
        "name": "run_block",
        "description": (
            "实时执行一个积木并返回结果。无需应用内开关；危险命令类（python_script/run_command）、"
            "电源操作（power_action）、控制流积木、自定义积木一律拒绝，其余（桌面动作/文件/图片处理/浏览器/系统等）全部可执行。"
            "响应结构：外层 ok/type/node_id/tier 是执行状态，积木的真实输出在嵌套 result 字段里"
            "（如 result.ok 为业务成败、result.output/result.items/result.error 为输出与错误），判断成败要看 result。"
            "坐标禁止臆造：先 capture_screen + locate_text_on_screen 获取真实坐标。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "积木 type"},
                "params": {"type": "object", "description": "积木参数（见 get_block_schema）"},
            },
            "required": ["type"],
        },
    },
    {
        "name": "run_flow",
        "description": (
            "执行 Nexuz 流程库中的一条流程（走完整参数校验与执行策略）。"
            "流程内含 python_script/run_command/power_action/自定义积木时整体拒绝（含子流程与定时再触发，运行期逐节点强制）。"
            "默认阻塞等待执行结束并返回结果摘要；等待超时返回 timed_out:true（流程仍在运行，可用 flow_control stop 止损）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_path": {"type": "string", "description": "流程库内的 .flow.json 文件路径（先用 list_flows 查询）"},
                "flow": {"type": "object", "description": "或直接内联 flow JSON"},
                "wait": {"type": "boolean", "default": True},
                "timeout_s": {"type": "number", "default": 300},
                "hide_window": {"type": "boolean", "default": True, "description": "运行时显示紧凑监视器"},
            },
        },
    },
    {
        "name": "list_flows",
        "description": "列出 Nexuz 流程库中的流程（name/path/mtime）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "flow_control",
        "description": "控制当前正在执行的流程：stop 急停 / pause 暂停 / resume 继续。",
        "inputSchema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["stop", "pause", "resume"]}},
            "required": ["action"],
        },
    },
    {
        "name": "capture_screen",
        "description": "截取整个虚拟桌面，返回截图（图像）与尺寸。用于观察屏幕，配合 locate_text_on_screen 定位文字坐标。",
        "inputSchema": {
            "type": "object",
            "properties": {"hide_window": {"type": "boolean", "default": True, "description": "截图前隐藏 Nexuz 主窗"}},
        },
    },
    {
        "name": "locate_text_on_screen",
        "description": "在已截图（或最近一张）上用 OCR 查找文字，返回中心点坐标与 point_ref。需先 capture_screen。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "match_text": {"type": "string"},
                "match_mode": {"type": "string", "enum": ["contains", "exact", "regex"], "default": "contains"},
                "shot_ref": {"type": "string", "description": "可选，capture_screen 返回的 shot_ref"},
                "label": {"type": "string", "description": "点位可读标签"},
            },
            "required": ["match_text"],
        },
    },
    {
        "name": "reset_session",
        "description": "清空 MCP 会话的跨调用变量上下文（run_block 输出的 {{绑定}} 缓存）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def log(msg: str) -> None:
    print(f"[nexuz-mcp] {msg}", file=sys.stderr, flush=True)


def port_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "Nexuz" / "mcp" / "port.json"


def read_endpoint() -> tuple[int, str] | None:
    try:
        data = json.loads(port_file().read_text(encoding="utf-8"))
        return int(data["port"]), str(data["token"])
    except Exception:
        return None


def http_json(method: str, port: int, token: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}{method}"
    req = urllib.request.Request(url, method="POST" if payload is not None else "GET")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    else:
        body = None
    with urllib.request.urlopen(req, body, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def health_ok(port: int, timeout: float = 1.5) -> dict | None:
    try:
        status, data = http_json("/health", port, "", None, timeout)
        if status == 200 and data.get("ok"):
            return data
    except Exception:
        pass
    return None


def launch_app() -> None:
    shell_dir = Path(__file__).resolve().parent
    exe = os.environ.get("NEXUZ_EXE", "").strip()
    try:
        if exe:
            subprocess.Popen(
                [exe],
                cwd=str(Path(exe).parent) if Path(exe).is_file() else None,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                close_fds=True,
            )
            log(f"launched NEXUZ_EXE: {exe}")
            return
        if (shell_dir / "main.py").is_file():
            subprocess.Popen([sys.executable, "main.py"], cwd=str(shell_dir), close_fds=True)
            log(f"launched dev app: {shell_dir / 'main.py'}")
            return
        if (shell_dir / "backend" / "main.py").is_file():
            subprocess.Popen(
                [sys.executable, str(shell_dir / "backend" / "main.py")],
                cwd=str(shell_dir),
                close_fds=True,
            )
            log(f"launched dev app: {shell_dir / 'backend' / 'main.py'}")
            return
        log("no way to launch Nexuz: NEXUZ_EXE not set and main.py not found next to shell")
    except Exception as exc:
        log(f"launch failed: {exc}")


def ensure_endpoint() -> tuple[int, str]:
    ep = read_endpoint()
    if ep and health_ok(ep[0]):
        return ep
    log("Nexuz not reachable — waking app")
    launch_app()
    deadline = time.monotonic() + WAKE_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(0.5)
        ep = read_endpoint()
        if ep and health_ok(ep[0]):
            log(f"Nexuz endpoint ready on port {ep[0]}")
            return ep
    raise RuntimeError(f"Nexuz 未就绪：{WAKE_TIMEOUT_S:.0f}s 内未能连接本地服务（应用可能启动失败）")


def call_tool(name: str, args: dict) -> dict:
    timeout = DEFAULT_CALL_TIMEOUT_S
    if name == "run_flow":
        wait = bool(args.get("wait", True))
        timeout = (float(args.get("timeout_s") or 300) + 60.0) if wait else DEFAULT_CALL_TIMEOUT_S
    port, token = ensure_endpoint()
    status, data = http_json("/rpc", port, token, {"tool": name, "args": args}, timeout)
    if status != 200:
        raise RuntimeError(f"Nexuz bridge HTTP {status}: {data.get('error', 'unknown')}")
    if not data.get("ok"):
        raise RuntimeError(f"Nexuz bridge error: {data.get('error', 'unknown')}")
    return data.get("result") or {}


def data_url_to_content(data_url: str) -> dict | None:
    prefix = "data:"
    if not data_url.startswith(prefix):
        return None
    try:
        head, b64 = data_url[len(prefix):].split(";base64,", 1)
        mime = head or "image/png"
        return {"type": "image", "data": b64, "mimeType": mime}
    except Exception:
        return None


def tool_result_content(name: str, result: dict) -> tuple[list[dict], bool]:
    ok = bool(result.get("ok", True))
    contents: list[dict] = []
    if name == "capture_screen" and ok and result.get("data_url"):
        img = data_url_to_content(str(result["data_url"]))
        if img:
            meta = {k: result.get(k) for k in ("shot_ref", "width", "height", "left", "top", "coord_space") if k in result}
            contents.append(img)
            contents.append({"type": "text", "text": json.dumps(meta, ensure_ascii=False)})
            return contents, False
    contents.append({"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)})
    return contents, not ok


def write_msg(msg: dict) -> None:
    # ensure_ascii=True keeps stdout bytes pure ASCII regardless of the
    # Windows console codepage (GBK etc.) — MCP clients decode UTF-8/ASCII.
    sys.stdout.write(json.dumps(msg, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def handle_request(req: dict, server_version: str) -> dict | None:
    method = str(req.get("method") or "")
    rid = req.get("id")
    params = req.get("params") or {}

    def reply(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def error(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    if method == "initialize":
        requested = str((params or {}).get("protocolVersion") or "")
        version = requested if requested in SUPPORTED_VERSIONS else DEFAULT_VERSION
        return reply(
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": server_version},
            }
        )
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": TOOLS})
    if method == "tools/call":
        name = str((params or {}).get("name") or "")
        args = (params or {}).get("arguments") or {}
        if not any(t["name"] == name for t in TOOLS):
            return error(-32602, f"unknown tool: {name}")
        try:
            result = call_tool(name, args if isinstance(args, dict) else {})
        except Exception as exc:
            return reply(
                {
                    "content": [{"type": "text", "text": f"Nexuz 调用失败: {exc}"}],
                    "isError": True,
                }
            )
        contents, is_error = tool_result_content(name, result if isinstance(result, dict) else {"result": result})
        out = {"content": contents}
        if is_error:
            out["isError"] = True
        return reply(out)
    if rid is None:
        return None  # notification we don't handle
    return error(-32601, f"method not found: {method}")


def main() -> int:
    # MCP stdio framing is UTF-8; don't inherit the Windows console codepage.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    server_version = "unknown"
    ep = read_endpoint()
    if ep:
        info = health_ok(ep[0])
        if info and info.get("version"):
            server_version = str(info["version"])
    log(f"stdio shell up (app version: {server_version})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        if not isinstance(req, dict):
            continue
        method = str(req.get("method") or "")
        if method == "notifications/initialized":
            continue
        try:
            resp = handle_request(req, server_version)
        except Exception as exc:
            log(f"handler crash: {exc}")
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32603, "message": f"internal error: {exc}"},
            }
        if resp is not None:
            write_msg(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
