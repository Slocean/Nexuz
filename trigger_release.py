#!/usr/bin/env python3
"""
本地一条命令触发 GitHub Actions 打包发版（不需要安装 gh）。

做法：按 app_update.json 里 history[0].version 打 tag 并 push —— workflow 监听 v* tag 自动跑。

  python trigger_release.py
  release.bat
  release.bat 0.1.1   # 可选：覆盖版本号
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def read_channel_version() -> str:
    path = ROOT / "app_update.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("history"), list) and data["history"]:
        first = data["history"][0]
        if isinstance(first, dict):
            ver = str(first.get("version") or "").strip().lstrip("v")
            if ver:
                return ver
    return str(data.get("version") or "").strip().lstrip("v") if isinstance(data, dict) else ""


def main() -> None:
    version = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lstrip("v")
    if not version:
        version = read_channel_version()
    if not version:
        raise SystemExit("没有版本号：请在 app_update.json 的 history[0].version 填写，或传参")

    tag = f"v{version}"
    print(f"打 tag {tag} 并推送到 origin -> 自动触发 Release Action")

    # 若 tag 已存在则删掉本地/远端再重建（方便同版本重打）
    subprocess.call(["git", "tag", "-d", tag], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.call(
        ["git", "push", "origin", f":refs/tags/{tag}"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])

    print("OK: 已推送 tag，去看打包进度：")
    print("  https://github.com/Slocean/Nexuz/actions")
    print("  https://github.com/Slocean/Nexuz/releases")


if __name__ == "__main__":
    main()
