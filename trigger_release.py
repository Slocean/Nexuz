#!/usr/bin/env python3
"""
本地一条命令触发 GitHub Actions 打包发版（不需要安装 gh）。

做法：按 app_update.json 里 history[0].version 打 tag 并 push —— workflow 监听 v* tag 自动跑。

  python trigger_release.py
  release.bat
  release.bat 0.1.1   # 可选：须与 app_update.json 当前版本一致

若同名 tag 已在远端/本地存在，会先删除再重打（用于修正同版本发版）；
低于远端其他最新版本的号仍会拒绝。
"""

from __future__ import annotations

import json
import subprocess
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def output(cmd: list[str]) -> str:
    return subprocess.check_output(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def version_key(version: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError("版本号必须是无前导零的 X.Y.Z，例如 0.4.1")
    return tuple(int(part) for part in match.groups())


def remote_versions() -> list[str]:
    raw = output(["git", "ls-remote", "--tags", "--refs", "origin", "refs/tags/v*"])
    versions: list[str] = []
    for line in raw.splitlines():
        ref = line.rsplit("\t", 1)[-1].strip()
        prefix = "refs/tags/v"
        if not ref.startswith(prefix):
            continue
        version = ref[len(prefix) :]
        if VERSION_RE.fullmatch(version):
            versions.append(version)
    return versions


def ensure_release_version_allowed(version: str, existing: list[str]) -> bool:
    """Validate version vs remote tags.

    Returns True when the same-version tag already exists and should be deleted
    before retagging. Versions lower than any *other* remote release are rejected.
    """
    target = version_key(version)
    replace_existing = version in existing
    peers = [v for v in existing if v != version]
    if peers:
        latest_peer = max(peers, key=version_key)
        if target <= version_key(latest_peer):
            raise SystemExit(
                f"版本必须递增：目标 v{version}，远端最新版本为 v{latest_peer}"
            )
    return replace_existing


# Backward-compatible name used by older tests/docs.
def assert_new_release_version(version: str, existing: list[str]) -> None:
    ensure_release_version_allowed(version, existing)


def delete_tag(tag: str, *, remote: bool) -> None:
    """Delete local and optionally remote tag. Missing local/remote is ignored."""
    if output(["git", "tag", "--list", tag]):
        run(["git", "tag", "-d", tag])
    if remote:
        # Prefer --delete; fall back to refspec delete. Ignore if already gone.
        try:
            run(["git", "push", "origin", "--delete", tag])
        except subprocess.CalledProcessError:
            try:
                run(["git", "push", "origin", f":refs/tags/{tag}"])
            except subprocess.CalledProcessError as exc:
                print(f"! 远端 tag {tag} 删除失败（可能已不存在）: {exc}")


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
    channel_version = read_channel_version()
    if not version:
        version = channel_version
    if not version:
        raise SystemExit("没有版本号：请在 app_update.json 的 history[0].version 填写，或传参")
    if version != channel_version:
        raise SystemExit(
            f"参数版本 v{version} 与 app_update.json 当前版本 v{channel_version} 不一致；"
            "请先更新发布清单"
        )

    try:
        versions = remote_versions()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"无法读取 origin 远端 tag，已中止发布：{exc}") from exc
    replace_existing = ensure_release_version_allowed(version, versions)

    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from backend.version_sync import sync_version_from_app_update

        sync_version_from_app_update(root=ROOT)
    except Exception as exc:
        print(f"! version sync skipped: {exc}")

    tag = f"v{version}"
    local_exists = bool(output(["git", "tag", "--list", tag]))
    if replace_existing or local_exists:
        print(f"发现已有 tag {tag}，先删除后再重打")
        delete_tag(tag, remote=replace_existing)

    print(f"打 tag {tag} 并推送到 origin -> 自动触发 Release Action")
    run(["git", "tag", tag])
    run(["git", "push", "origin", tag])

    print("OK: 已推送 tag，去看打包进度：")
    print("  https://github.com/Slocean/Nexuz/actions")
    print("  https://github.com/Slocean/Nexuz/releases")


if __name__ == "__main__":
    main()
