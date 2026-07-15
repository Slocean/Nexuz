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


def _http_github_json(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("unexpected GitHub API payload")
    return data


def _normalize_channel(raw: Any) -> dict[str, Any]:
    """Normalize app_update.json into {history: [{version,title,body,notice}, ...]} (newest first)."""
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        if isinstance(raw.get("history"), list):
            entries = raw["history"]
        else:
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
        notice = str(item.get("notice") or "").strip()
        if not ver and not title and not body and not notice:
            continue
        history.append(
            {
                "version": ver,
                "title": title or (f"{ver} 更新" if ver else "更新公告"),
                "body": body,
                "notice": notice,
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
                "notice": str(item.get("notice") or ""),
            }
        )
    return out


def _notice_id(body: str) -> str:
    import hashlib

    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def resolve_notice(channel: dict[str, Any]) -> dict[str, Any] | None:
    """Pick notice from newest history entry; if empty, walk older entries."""
    for item in channel.get("history") or []:
        if not isinstance(item, dict):
            continue
        body = str(item.get("notice") or "").strip()
        if not body:
            continue
        ver = str(item.get("version") or "").strip()
        return {
            "id": _notice_id(body),
            "title": "通知",
            "body": body,
            "version": ver,
            "from_version": ver,
        }
    return None


def fetch_notice() -> dict[str, Any]:
    """Startup / megaphone: sticky notice (not the version changelog)."""
    ch = fetch_channel(prefer_remote=True)
    if not ch.get("ok"):
        return {"ok": False, "error": ch.get("error") or "获取通知失败"}
    notice = resolve_notice(ch["channel"])
    if not notice:
        return {
            "ok": True,
            "notice": None,
            "message": "暂无通知",
            "source": ch.get("source"),
        }
    return {"ok": True, "notice": notice, "source": ch.get("source")}


def fetch_announcement() -> dict[str, Any]:
    """Settings: version changelog history (title/body), plus resolved notice for reference."""
    ch = fetch_channel(prefer_remote=True)
    if not ch.get("ok"):
        return {"ok": False, "error": ch.get("error") or "获取公告失败"}
    channel = ch["channel"]
    history = _history_list(channel)
    ann = _announcement_from_channel(channel)
    notice = resolve_notice(channel)
    if not ann and not history:
        return {
            "ok": True,
            "announcement": None,
            "history": [],
            "notice": notice,
            "message": "暂无公告",
            "source": ch.get("source"),
        }
    return {
        "ok": True,
        "announcement": ann,
        "history": history,
        "notice": notice,
        "source": ch.get("source"),
    }


def _default_download_url(version: str) -> str:
    ver = str(version).lstrip("v")
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/v{ver}/{ASSET_NAME}"
    )


def _pick_exe_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower() == ASSET_NAME.lower():
            return asset
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower().endswith(".exe"):
            return asset
    return None


def resolve_download_url(version: str | None = None) -> dict[str, Any]:
    """Resolve a real browser_download_url from GitHub Releases (tag -> latest)."""
    ver = str(version or "").lstrip("v").strip()
    tried: list[str] = []

    def from_release(release: dict[str, Any]) -> dict[str, Any] | None:
        asset = _pick_exe_asset(release)
        if not asset:
            return None
        url = str(asset.get("browser_download_url") or "").strip()
        if not url:
            return None
        tag = str(release.get("tag_name") or "").lstrip("v").strip()
        return {
            "ok": True,
            "download_url": url,
            "asset_name": asset.get("name") or ASSET_NAME,
            "asset_size": asset.get("size"),
            "latest_version": tag or ver,
            "html_url": release.get("html_url") or RELEASES_PAGE_URL,
        }

    if ver:
        tag_url = (
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/v{ver}"
        )
        tried.append(tag_url)
        try:
            hit = from_release(_http_github_json(tag_url))
            if hit:
                return hit
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return {
                    "ok": False,
                    "error": f"查询 Release 失败 HTTP {exc.code}",
                    "tried": tried,
                    "html_url": RELEASES_PAGE_URL,
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tried": tried, "html_url": RELEASES_PAGE_URL}

    latest_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    tried.append(latest_url)
    try:
        hit = from_release(_http_github_json(latest_url))
        if hit:
            return hit
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": False,
                "error": "GitHub 上还没有可下载的 Release（或尚未上传 Nexuz.exe）",
                "html_url": RELEASES_PAGE_URL,
                "tried": tried,
            }
        return {
            "ok": False,
            "error": f"查询最新 Release 失败 HTTP {exc.code}",
            "tried": tried,
            "html_url": RELEASES_PAGE_URL,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tried": tried, "html_url": RELEASES_PAGE_URL}

    return {
        "ok": False,
        "error": "未找到可下载的 Nexuz.exe，请确认 Release 已上传该资源",
        "html_url": RELEASES_PAGE_URL,
        "tried": tried,
    }


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

    resolved = resolve_download_url(latest)
    download_url = resolved.get("download_url") if resolved.get("ok") else None
    html_url = resolved.get("html_url") or (
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
        "asset_name": resolved.get("asset_name") or ASSET_NAME,
        "asset_size": resolved.get("asset_size"),
        "asset_ready": bool(resolved.get("ok") and download_url),
        "asset_error": None if resolved.get("ok") else resolved.get("error"),
        "source": ch.get("source"),
        "message": f"发现新版本 {latest}" if available else "已是最新版本",
    }


def download_update(download_url: str | None = None) -> dict[str, Any]:
    """Download latest (or given) exe next to the running binary as Nexuz_update.exe."""
    info = check_for_update()
    if not info.get("ok"):
        return info

    if not info.get("update_available") and not download_url:
        return {
            "ok": False,
            "error": "当前已是最新版本，无需下载",
            "current_version": info.get("current_version"),
            "latest_version": info.get("latest_version"),
        }

    url = (download_url or "").strip()
    if not url:
        resolved = resolve_download_url(info.get("latest_version"))
        if not resolved.get("ok"):
            return {
                "ok": False,
                "error": resolved.get("error")
                or "GitHub Release 中没有 Nexuz.exe，请先成功发版或到 Releases 手动下载",
                "html_url": resolved.get("html_url")
                or info.get("html_url")
                or RELEASES_PAGE_URL,
                "current_version": info.get("current_version"),
                "latest_version": info.get("latest_version"),
            }
        url = str(resolved.get("download_url") or "").strip()

    if not url:
        return {
            "ok": False,
            "error": "未找到可下载地址，请到 GitHub Releases 手动下载",
            "html_url": info.get("html_url") or RELEASES_PAGE_URL,
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
    except urllib.error.HTTPError as exc:
        try:
            if partial.exists():
                partial.unlink()
        except OSError:
            pass
        hint = info.get("html_url") or RELEASES_PAGE_URL
        if exc.code == 404:
            return {
                "ok": False,
                "error": (
                    f"下载失败 HTTP 404：Release 里还没有 Nexuz.exe"
                    f"（目标版本 {info.get('latest_version')}）。"
                    f"请确认已成功发版，或打开 Releases 手动下载。\n{hint}"
                ),
                "html_url": hint,
            }
        return {"ok": False, "error": f"下载失败 HTTP {exc.code}", "html_url": hint}
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
        "message": f"已下载 {info.get('latest_version')}，可立即更新并重启",
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
