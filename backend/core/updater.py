"""Check updates / announcements from app_update.json; download exe from Release."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend.paths import exe_dir, project_root
from backend.version import (
    APP_UPDATE_FILE,
    APP_UPDATE_URL,
    GITHUB_OWNER,
    GITHUB_REPO,
    RELEASES_PAGE_URL,
    __version__,
)

USER_AGENT = f"Nexuz/{__version__} (+https://github.com/{GITHUB_OWNER}/{GITHUB_REPO})"
ASSET_NAME = "Nexuz.exe"
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)", re.I)


def current_version() -> str:
    return str(__version__).lstrip("v").strip() or "0.0.0"


def _parse_version(text: str) -> tuple[int, ...]:
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return (0,)
    return tuple(int(p) for p in m.group(1).split("."))


def version_gt(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _http_json(url: str, *, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _http_bytes(url: str, *, timeout: float = 600.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _normalize_channel(raw: Any) -> dict[str, Any]:
    """Normalize app_update.json into {history: [{version,title,body}, ...]} (newest first)."""
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        if isinstance(raw.get("history"), list):
            entries = raw["history"]
        else:
            # Legacy flat {version, title, body}
            entries = [raw]
    else:
        entries = []

    history: list[dict[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        ver = str(item.get("version") or "").lstrip("v").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not ver and not title and not body:
            continue
        history.append(
            {
                "version": ver,
                "title": title or (f"{ver} 更新" if ver else "更新公告"),
                "body": body,
            }
        )
    return {"history": history}


def _load_local_channel() -> dict[str, Any] | None:
    try:
        path = project_root() / APP_UPDATE_FILE
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_channel(raw)
    except Exception:
        return None


def fetch_channel(*, prefer_remote: bool = True) -> dict[str, Any]:
    """Load app_update.json (remote main, then local fallback). Always normalized."""
    remote_err: str | None = None
    if prefer_remote:
        try:
            data = _normalize_channel(_http_json(APP_UPDATE_URL, timeout=15.0))
            return {"ok": True, "source": "remote", "channel": data}
        except urllib.error.HTTPError as exc:
            remote_err = f"HTTP {exc.code}"
        except Exception as exc:
            remote_err = str(exc)

    local = _load_local_channel()
    if local is not None:
        return {
            "ok": True,
            "source": "local",
            "channel": local,
            "remote_error": remote_err,
        }
    if remote_err:
        return {"ok": False, "error": f"无法读取更新通道: {remote_err}"}
    return {"ok": False, "error": f"缺少 {APP_UPDATE_FILE}"}


def _latest_entry(channel: dict[str, Any]) -> dict[str, str] | None:
    history = channel.get("history") or []
    if not history:
        return None
    first = history[0]
    return first if isinstance(first, dict) else None


def _announcement_from_channel(channel: dict[str, Any]) -> dict[str, Any] | None:
    entry = _latest_entry(channel)
    if not entry:
        return None
    ver = entry.get("version") or ""
    title = entry.get("title") or ""
    body = entry.get("body") or ""
    if not body and not title:
        return None
    return {
        "id": ver or None,
        "version": ver,
        "title": title or "更新公告",
        "body": body,
        "link": RELEASES_PAGE_URL,
    }


def _history_list(channel: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in channel.get("history") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "version": str(item.get("version") or ""),
                "title": str(item.get("title") or ""),
                "body": str(item.get("body") or ""),
            }
        )
    return out


def _default_download_url(version: str) -> str:
    ver = str(version).lstrip("v")
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/v{ver}/{ASSET_NAME}"
    )


def check_for_update() -> dict[str, Any]:
    local = current_version()
    ch = fetch_channel(prefer_remote=True)
    if not ch.get("ok"):
        return {"ok": False, "error": ch.get("error") or "检查更新失败", "current_version": local}

    channel = ch["channel"]
    history = _history_list(channel)
    entry = _latest_entry(channel)
    latest = (entry or {}).get("version") or local
    ann = _announcement_from_channel(channel)
    notes = str(ann.get("body") or "") if ann else ""
    download_url = _default_download_url(latest) if latest else None
    html_url = (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/v{latest}"
        if latest
        else RELEASES_PAGE_URL
    )

    available = version_gt(latest, local)
    return {
        "ok": True,
        "update_available": available,
        "current_version": local,
        "latest_version": latest,
        "release_notes": notes,
        "announcement": ann,
        "history": history,
        "html_url": html_url,
        "download_url": download_url,
        "asset_name": ASSET_NAME,
        "source": ch.get("source"),
        "message": f"发现新版本 {latest}" if available else "已是最新版本",
    }


def fetch_announcement() -> dict[str, Any]:
    """Latest announcement + full cumulative history from app_update.json."""
    ch = fetch_channel(prefer_remote=True)
    if not ch.get("ok"):
        return {"ok": False, "error": ch.get("error") or "获取公告失败"}
    channel = ch["channel"]
    history = _history_list(channel)
    ann = _announcement_from_channel(channel)
    if not ann and not history:
        return {"ok": True, "announcement": None, "history": [], "message": "暂无公告", "source": ch.get("source")}
    return {
        "ok": True,
        "announcement": ann,
        "history": history,
        "source": ch.get("source"),
    }

def download_update(download_url: str | None = None) -> dict[str, Any]:
    """Download latest (or given) exe next to the running binary as Nexuz_update.exe."""
    info = check_for_update()
    if not info.get("ok"):
        return info
    url = (download_url or info.get("download_url") or "").strip()
    if not url:
        return {
            "ok": False,
            "error": "未找到可下载地址，请到 GitHub Releases 手动下载",
            "html_url": info.get("html_url") or RELEASES_PAGE_URL,
        }
    if not info.get("update_available") and not download_url:
        return {
            "ok": False,
            "error": "当前已是最新版本，无需下载",
            "current_version": info.get("current_version"),
            "latest_version": info.get("latest_version"),
        }

    dest_dir = exe_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "Nexuz_update.exe"
    partial = dest.with_suffix(".exe.partial")

    try:
        blob = _http_bytes(url)
        if len(blob) < 1024 * 100:
            return {"ok": False, "error": "下载文件过小，可能不是有效的安装包"}
        partial.write_bytes(blob)
        if dest.exists():
            dest.unlink()
        partial.rename(dest)
    except Exception as exc:
        try:
            if partial.exists():
                partial.unlink()
        except OSError:
            pass
        return {"ok": False, "error": f"下载失败: {exc}"}

    return {
        "ok": True,
        "path": str(dest),
        "size": dest.stat().st_size,
        "latest_version": info.get("latest_version"),
        "current_version": info.get("current_version"),
        "message": f"已下载 {info.get('latest_version')}，点击「立即更新」将替换并重启",
    }


def _target_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return exe_dir() / "Nexuz.exe"


def apply_update_and_restart() -> dict[str, Any]:
    """Swap in downloaded exe via a helper bat, then exit the app."""
    if not getattr(sys, "frozen", False):
        return {
            "ok": False,
            "error": "开发模式下请直接拉取代码或手动替换打包产物，无法热更新 exe",
        }

    update_path = exe_dir() / "Nexuz_update.exe"
    if not update_path.is_file():
        return {"ok": False, "error": "未找到已下载的更新包，请先下载更新"}

    target = _target_exe_path()
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"nexuz_apply_update_{pid}.bat"
    upd = str(update_path)
    tgt = str(target)
    work = str(target.parent)
    script = f"""@echo off
chcp 65001 >nul
setlocal
set "PID={pid}"
set "UPD={upd}"
set "TGT={tgt}"
set "WORK={work}"
:wait
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
timeout /t 1 /nobreak >nul
copy /Y "%UPD%" "%TGT%" >nul
if errorlevel 1 (
  echo Nexuz update failed: cannot replace exe
  pause
  exit /b 1
)
del /F /Q "%UPD%" >nul 2>&1
start "" /D "%WORK%" "%TGT%"
del /F /Q "%~f0" >nul 2>&1
"""
    try:
        bat.write_text(script, encoding="utf-8")
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat)],
            cwd=str(target.parent),
            creationflags=0x00000008 | 0x08000000,  # DETACHED_PROCESS | CREATE_NO_WINDOW
            close_fds=True,
        )
    except Exception as exc:
        return {"ok": False, "error": f"无法启动更新脚本: {exc}"}

    return {
        "ok": True,
        "restarting": True,
        "message": "即将退出并应用更新…",
    }


def open_releases_page() -> dict[str, Any]:
    try:
        import webbrowser

        webbrowser.open(RELEASES_PAGE_URL)
        return {"ok": True, "url": RELEASES_PAGE_URL}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": RELEASES_PAGE_URL}
