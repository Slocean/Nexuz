"""Check updates / announcements from app_update.json; download exe from Release."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
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
CHECKSUM_ASSET_NAME = f"{ASSET_NAME}.sha256"
VERIFY_METADATA_NAME = "Nexuz_update.verify.json"
_GITHUB_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)", re.I)
_SHA256_RE = re.compile(r"^([0-9a-fA-F]{64})\s+[ *]?(.+?)\s*$")


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


def _http_bytes(
    url: str,
    *,
    timeout: float = 600.0,
    on_progress: Any | None = None,
) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_TrustedGitHubRedirectHandler())
    with opener.open(req, timeout=timeout) as resp:
        total = 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        chunks: list[bytes] = []
        read = 0
        while True:
            block = resp.read(256 * 1024)
            if not block:
                break
            chunks.append(block)
            read += len(block)
            if on_progress:
                try:
                    pct = (read * 100.0 / total) if total > 0 else None
                    on_progress(read, total, pct)
                except Exception:
                    pass
        return b"".join(chunks)


def _validate_github_url(url: str, *, initial: bool = False) -> str:
    """Only allow HTTPS assets served by GitHub's release infrastructure."""
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in _GITHUB_DOWNLOAD_HOSTS:
        raise ValueError("更新地址必须是受信任的 GitHub HTTPS Release 资源")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("更新地址包含不允许的认证信息或端口")
    if initial:
        prefix = f"/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
        if host != "github.com" or not parsed.path.startswith(prefix):
            raise ValueError("更新地址不属于配置的 GitHub 仓库 Release")
    return urllib.parse.urlunsplit(parsed)


class _TrustedGitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that leave GitHub's release asset hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url = _validate_github_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


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
    return None


def _pick_named_asset(release: dict[str, Any], expected_name: str) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower() == expected_name.lower():
            return asset
    return None


def resolve_download_url(version: str | None = None) -> dict[str, Any]:
    """Resolve browser_download_url for a specific Release tag.

    When ``version`` is set, only that tag is accepted. Never silently fall back
    to ``/releases/latest`` — that used to hand users an older exe while the UI
    still claimed the newer channel version (forcing a second update later).
    """
    ver = str(version or "").lstrip("v").strip()
    tried: list[str] = []

    def from_release(release: dict[str, Any]) -> dict[str, Any] | None:
        asset = _pick_exe_asset(release)
        if not asset:
            return None
        checksum_asset = _pick_named_asset(release, CHECKSUM_ASSET_NAME)
        if not checksum_asset:
            return None
        try:
            url = _validate_github_url(
                str(asset.get("browser_download_url") or "").strip(),
                initial=True,
            )
            checksum_url = _validate_github_url(
                str(checksum_asset.get("browser_download_url") or "").strip(),
                initial=True,
            )
        except ValueError:
            return None
        tag = str(release.get("tag_name") or "").lstrip("v").strip()
        return {
            "ok": True,
            "download_url": url,
            "checksum_url": checksum_url,
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
        html = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/v{ver}"
        try:
            hit = from_release(_http_github_json(tag_url))
            if hit:
                # Guard against a mismatched tag payload.
                got = str(hit.get("latest_version") or "").lstrip("v").strip()
                if got and got != ver:
                    return {
                        "ok": False,
                        "error": (
                            f"Release 版本不匹配：通道要求 v{ver}，"
                            f"但拿到的是 v{got}。请等待对应 Release 发布完成。"
                        ),
                        "tried": tried,
                        "html_url": html,
                        "pending": True,
                    }
                return hit
            return {
                "ok": False,
                "error": (
                    f"v{ver} 的 Release 已存在，但还没有完整的 "
                    f"{ASSET_NAME} + {CHECKSUM_ASSET_NAME} 校验资源。"
                    f"打包可能仍在进行或失败，请稍后再试。"
                ),
                "tried": tried,
                "html_url": html,
                "pending": True,
            }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {
                    "ok": False,
                    "error": (
                        f"v{ver} 尚未发布（Release 不存在或 exe 未上传）。"
                        f"通道已宣告该版本时，通常是打包还在跑——请稍后再检查更新。"
                    ),
                    "tried": tried,
                    "html_url": html,
                    "pending": True,
                }
            return {
                "ok": False,
                "error": f"查询 Release 失败 HTTP {exc.code}",
                "tried": tried,
                "html_url": html,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tried": tried, "html_url": html}

    # No target version: resolve whatever GitHub considers latest.
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
    asset_ready = bool(resolved.get("ok") and download_url)
    pending = bool(resolved.get("pending"))
    if available and not asset_ready:
        message = (
            f"发现新版本 {latest}，但安装包尚未就绪"
            + ("（发布仍在进行中，请稍后再试）" if pending else "")
        )
    elif available:
        message = f"发现新版本 {latest}"
    else:
        message = "已是最新版本"
    return {
        "ok": True,
        "update_available": available,
        "current_version": local,
        "latest_version": latest,
        "release_notes": notes,
        "announcement": ann,
        "history": history,
        "html_url": html_url,
        # Never return a URL for a different release than `latest`.
        "download_url": download_url if asset_ready else None,
        "checksum_url": resolved.get("checksum_url") if asset_ready else None,
        "asset_name": resolved.get("asset_name") or ASSET_NAME,
        "asset_size": resolved.get("asset_size") if asset_ready else None,
        "asset_ready": asset_ready,
        "asset_pending": pending,
        "asset_error": None if resolved.get("ok") else resolved.get("error"),
        "source": ch.get("source"),
        "message": message,
    }


def _parse_checksum_manifest(raw: bytes) -> str:
    text = raw.decode("utf-8-sig", errors="strict")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SHA256_RE.match(line)
        if not match:
            continue
        digest, filename = match.groups()
        if Path(filename.strip()).name.lower() == ASSET_NAME.lower():
            return digest.lower()
    raise ValueError(f"{CHECKSUM_ASSET_NAME} 中缺少 {ASSET_NAME} 的有效 SHA-256")


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    *,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Download and verify the latest release next to the running executable."""
    info = check_for_update()
    if not info.get("ok"):
        return info

    if not info.get("update_available"):
        return {
            "ok": False,
            "error": "当前已是最新版本，无需下载",
            "current_version": info.get("current_version"),
            "latest_version": info.get("latest_version"),
        }

    resolved = resolve_download_url(info.get("latest_version"))
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error")
            or "GitHub Release 缺少安装包或 SHA-256 清单，请到 Releases 手动下载",
            "html_url": resolved.get("html_url") or info.get("html_url") or RELEASES_PAGE_URL,
            "current_version": info.get("current_version"),
            "latest_version": info.get("latest_version"),
        }
    try:
        url = _validate_github_url(str(resolved.get("download_url") or ""), initial=True)
        checksum_url = _validate_github_url(
            str(resolved.get("checksum_url") or ""),
            initial=True,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "html_url": info.get("html_url")}

    dest_dir = exe_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "Nexuz_update.exe"
    partial = dest.with_suffix(".exe.partial")

    last_emit = [0.0]

    def _progress(read: int, total: int, pct: float | None) -> None:
        if not on_progress:
            return
        import time as _time

        now = _time.time()
        # Throttle UI emits
        if pct is not None and (pct >= 100 or now - last_emit[0] >= 0.2):
            last_emit[0] = now
            on_progress(
                {
                    "downloaded": read,
                    "total": total,
                    "percent": float(pct),
                    "message": f"正在下载… {int(pct)}%" if pct is not None else "正在下载…",
                }
            )

    try:
        if on_progress:
            on_progress({"downloaded": 0, "total": 0, "percent": 0, "message": "开始下载…"})
        expected_sha256 = _parse_checksum_manifest(
            _http_bytes(checksum_url, timeout=30.0)
        )
        blob = _http_bytes(url, on_progress=_progress if on_progress else None)
        if len(blob) < 1024 * 100:
            return {"ok": False, "error": "下载文件过小，可能不是有效的安装包"}
        actual_sha256 = _sha256_bytes(blob)
        if actual_sha256 != expected_sha256:
            return {
                "ok": False,
                "error": (
                    "安装包 SHA-256 校验失败，已拒绝更新。"
                    f"期望 {expected_sha256}，实际 {actual_sha256}"
                ),
            }
        partial.write_bytes(blob)
        if dest.exists():
            dest.unlink()
        partial.rename(dest)
        metadata = dest_dir / VERIFY_METADATA_NAME
        metadata.write_text(
            json.dumps(
                {
                    "version": info.get("latest_version"),
                    "sha256": expected_sha256,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if on_progress:
            on_progress(
                {
                    "downloaded": len(blob),
                    "total": len(blob),
                    "percent": 100,
                    "message": "下载完成",
                }
            )
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
        "sha256": expected_sha256,
        "latest_version": info.get("latest_version"),
        "current_version": info.get("current_version"),
        "message": f"已下载 {info.get('latest_version')}，可立即更新并重启",
    }


def _ps_escape(path: str) -> str:
    return str(path).replace("'", "''")


def _target_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return exe_dir() / "Nexuz.exe"


def _powershell_exe() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def cleanup_old_exe() -> None:
    """Remove leftover Nexuz.exe.old after a successful update restart."""
    try:
        old = exe_dir() / "Nexuz.exe.old"
        if old.is_file():
            old.unlink()
    except OSError:
        pass


def apply_update_and_restart() -> dict[str, Any]:
    """整包替换：下载好的新 exe 改成和旧版同名，再启动。

    不能边跑边删旧文件（Windows 锁住正在运行的 exe），所以顺序是：
      1. 新包已下到 Nexuz_update.exe（名字先不同，避免覆盖正在跑的文件）
      2. 启动助手后，本进程退出
      3. 助手：删掉旧 Nexuz.exe → 把 Nexuz_update.exe 改名为 Nexuz.exe → 启动
    """
    if not getattr(sys, "frozen", False):
        return {
            "ok": False,
            "error": (
                "当前不是打包后的 Nexuz.exe（开发模式）。"
                "热更新只替换正在运行的可执行文件，请用 Release 里的 exe 测试。"
            ),
        }

    update_path = exe_dir() / "Nexuz_update.exe"
    if not update_path.is_file():
        return {"ok": False, "error": "未找到已下载的更新包（Nexuz_update.exe），请先下载更新"}

    metadata_path = exe_dir() / VERIFY_METADATA_NAME
    try:
        if update_path.stat().st_size < 1024 * 100:
            return {"ok": False, "error": "更新包过小，可能下载不完整，请重新下载"}
        if not metadata_path.is_file():
            return {"ok": False, "error": "更新包缺少校验记录，请删除后重新下载"}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected_sha256 = str(metadata.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            return {"ok": False, "error": "更新包校验记录无效，请删除后重新下载"}
        actual_sha256 = _sha256_file(update_path)
        if actual_sha256 != expected_sha256:
            return {"ok": False, "error": "更新包在下载后发生变化，已拒绝应用"}
    except OSError as exc:
        return {"ok": False, "error": f"无法读取更新包: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"更新包安全校验失败: {exc}"}

    target = _target_exe_path()
    pid = os.getpid()
    work_dir = target.parent
    log_path = exe_dir() / "nexuz_update.log"

    upd = _ps_escape(str(update_path))
    tgt = _ps_escape(str(target))
    work = _ps_escape(str(work_dir))
    log = _ps_escape(str(log_path))
    verify_meta = _ps_escape(str(metadata_path))
    tgt_name = _ps_escape(target.name)

    ps1 = Path(tempfile.gettempdir()) / f"nexuz_apply_update_{pid}.ps1"
    vbs = Path(tempfile.gettempdir()) / f"nexuz_apply_update_{pid}.vbs"

    script = f"""
$ErrorActionPreference = 'Continue'
$pidToWait = {pid}
$upd = '{upd}'
$tgt = '{tgt}'
$work = '{work}'
$log = '{log}'
$verifyMeta = '{verify_meta}'
$tgtName = '{tgt_name}'

function Write-Log([string]$msg) {{
  $line = "[{{0}}] {{1}}" -f (Get-Date -Format o), $msg
  try {{ Add-Content -LiteralPath $log -Value $line -Encoding UTF8 }} catch {{}}
}}

function Show-Fail([string]$msg) {{
  Write-Log $msg
  try {{
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($msg, 'Nexuz 更新失败') | Out-Null
  }} catch {{}}
}}

Write-Log "wait exit pid=$pidToWait"
$exited = $false
for ($i = 0; $i -lt 120; $i++) {{
  if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) {{
    $exited = $true
    break
  }}
  Start-Sleep -Milliseconds 500
}}
if (-not $exited) {{
  Show-Fail "等待程序退出超时。日志: $log"
  exit 1
}}
Start-Sleep -Milliseconds 600

# 删旧 → 新文件改成同名（文件锁时短暂重试）
$ok = $false
for ($i = 0; $i -lt 40; $i++) {{
  try {{
    if (Test-Path -LiteralPath $tgt) {{
      Remove-Item -LiteralPath $tgt -Force
    }}
    Rename-Item -LiteralPath $upd -NewName $tgtName -Force
    $ok = $true
    Write-Log "deleted old, renamed new to $tgtName"
    break
  }} catch {{
    Write-Log ("try $($i+1): " + $_.Exception.Message)
    Start-Sleep -Milliseconds 500
  }}
}}

function Start-Nexuz([string]$exePath) {{
  # 下载/刚改名的文件可能仍被 Defender 扫描；PowerShell Start-Process
  # 直接拉起时，PyInstaller 解压 python*.dll 偶发失败（手动双击却正常）。
  try {{ Unblock-File -LiteralPath $exePath -ErrorAction SilentlyContinue }} catch {{}}
  for ($w = 0; $w -lt 20; $w++) {{
    try {{
      $fs = [System.IO.File]::Open($exePath, 'Open', 'Read', 'Read')
      $fs.Close()
      break
    }} catch {{
      Start-Sleep -Milliseconds 250
    }}
  }}
  Start-Sleep -Milliseconds 1500
  # 用 explorer 启动，模拟用户双击，避免继承隐藏 PowerShell 的环境
  $started = $false
  try {{
    Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $exePath + '"')
    $started = $true
    Write-Log "start via explorer: $exePath"
  }} catch {{
    Write-Log ("explorer start failed: " + $_.Exception.Message)
  }}
  if (-not $started) {{
    try {{
      Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','start','','/D',("`"$work`""),("`"$exePath`"") -WindowStyle Hidden
      Write-Log "start via cmd: $exePath"
      $started = $true
    }} catch {{
      Write-Log ("cmd start failed: " + $_.Exception.Message)
      Start-Process -FilePath $exePath -WorkingDirectory $work
      Write-Log "start via Start-Process: $exePath"
    }}
  }}
}}

if ($ok -and (Test-Path -LiteralPath $tgt)) {{
  Remove-Item -LiteralPath $verifyMeta -Force -ErrorAction SilentlyContinue
  Write-Log "start $tgt"
  Start-Nexuz $tgt
}} elseif (Test-Path -LiteralPath $upd) {{
  Write-Log "fallback start downloaded exe"
  Start-Nexuz $upd
  Show-Fail "删不掉旧版（可能被占用）。已直接启动下载的新版本。日志: $log"
}} else {{
  Show-Fail "更新失败。日志: $log"
  exit 1
}}

Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
    try:
        ps1.write_text(script, encoding="utf-8")
        ps_exe = _powershell_exe()
        vbs_body = (
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.Run """{ps_exe}"" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{ps1}""", 0, False\r\n'
        )
        vbs.write_text(vbs_body, encoding="ascii", errors="replace")

        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            ["wscript.exe", "//B", "//Nologo", str(vbs)],
            cwd=str(work_dir),
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            close_fds=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        return {"ok": False, "error": f"无法启动更新助手: {exc}"}

    return {
        "ok": True,
        "restarting": True,
        "log": str(log_path),
        "message": "即将退出：删除旧版，把新版改名为 Nexuz.exe 并启动…",
    }


def open_releases_page() -> dict[str, Any]:
    try:
        import webbrowser

        webbrowser.open(RELEASES_PAGE_URL)
        return {"ok": True, "url": RELEASES_PAGE_URL}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": RELEASES_PAGE_URL}
