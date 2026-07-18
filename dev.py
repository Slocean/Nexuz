#!/usr/bin/env python3
"""One-command Nexuz dev launcher: Vite + pywebview desktop window."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DEV_HOST = "127.0.0.1"
DEV_PORT = 5173
DEV_URL = f"http://{DEV_HOST}:{DEV_PORT}"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _wait_for_vite(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(DEV_HOST, DEV_PORT):
            return True
        time.sleep(0.25)
    return False


def _npm_cmd() -> list[str]:
    # Windows: npm is npm.cmd
    if sys.platform == "win32":
        return ["npm.cmd", "run", "dev"]
    return ["npm", "run", "dev"]


def main() -> int:
    if not (FRONTEND / "package.json").exists():
        print("找不到 frontend/package.json，请在项目根目录运行。")
        return 1

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from backend.version_sync import sync_version_from_app_update

        sync_version_from_app_update(root=ROOT)
    except Exception as exc:
        print(f"[Nexuz] 版本同步跳过: {exc}")

    env = os.environ.copy()
    env["NEXUZ_DEV_URL"] = DEV_URL

    print(f"[Nexuz] 启动 Vite → {DEV_URL}")
    vite = subprocess.Popen(
        _npm_cmd(),
        cwd=str(FRONTEND),
        env=env,
        # Keep Vite output visible in the same console
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    try:
        if not _wait_for_vite():
            print("[Nexuz] Vite 启动超时，请检查 frontend 依赖是否已 npm install。")
            _stop(vite)
            return 1

        print("[Nexuz] Vite 就绪，启动桌面窗口…")
        # Run desktop in-process so Ctrl+C / window close ends cleanly with us
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        # Ensure --dev is present for resolve_ui_url / debug
        if "--dev" not in sys.argv:
            sys.argv.append("--dev")

        from backend.main import main as desktop_main

        desktop_main()
        return 0
    except KeyboardInterrupt:
        print("\n[Nexuz] 已中断")
        return 0
    finally:
        _stop(vite)


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    print("[Nexuz] 关闭 Vite…")
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
