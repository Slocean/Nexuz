"""MCP 工具调用助手：经 nexuz_mcp.py stdio 完整握手后调用一个工具。

用法: python _mcp_tool.py <tool> [json_args]
输出: 工具结果的 JSON 文本
"""

import json
import sys

sys.path.insert(0, ".")

import subprocess

_id = 0


def rpc(proc, method, params=None):
    global _id
    _id += 1
    req = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        req["params"] = params
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"no response for {method}")
        resp = json.loads(line)
        if resp.get("id") == _id:
            return resp


def main() -> int:
    tool = sys.argv[1] if len(sys.argv) > 1 else "get_status"
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    proc = subprocess.Popen(
        [sys.executable, "nexuz_mcp.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        init = rpc(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "zcode-test", "version": "0.0.1"},
        })
        server = init["result"]["serverInfo"]
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        resp = rpc(proc, "tools/call", {"name": tool, "arguments": args})
        result = resp["result"]
        is_error = result.get("isError", False)
        import base64
        import os

        for c in result.get("content", []):
            if c.get("type") == "image":
                out = os.environ.get("TEMP", ".") + "/mcp_tool_image.png"
                open(out, "wb").write(base64.b64decode(c["data"]))
                print(f"# image saved: {out} ({c.get('mimeType')})")
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        print(f"# server={server['name']}@{server['version']} isError={is_error}")
        for t in texts:
            print(t)
        return 1 if is_error else 0
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
