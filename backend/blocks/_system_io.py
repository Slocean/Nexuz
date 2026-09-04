"""Shared helpers for system IO blocks (clipboard, files, paths)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Soft cap for file_io read to avoid blowing up UI / context memory.
MAX_FILE_READ_BYTES = 2 * 1024 * 1024

# 盘符相对路径（如 D:nexuz）：反斜杠丢失后的典型产物（常见于 JSON 转义错误）。
# resolve() 会把它静默锚定到该盘符当前目录，产生"路径被拼接"的错觉，直接拒绝并指路。
_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:(?![\\/])")


def clipboard_write(text: str) -> dict[str, Any]:
    """Copy text to the system clipboard via tkinter."""
    raw = "" if text is None else str(text)
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(raw)
        root.update()
        root.destroy()
        return {"ok": True, "text": raw}
    except Exception as exc:
        return {"ok": False, "text": raw, "error": str(exc)}


def clipboard_read() -> dict[str, Any]:
    """Read text from the system clipboard via tkinter."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update()
        try:
            text = root.clipboard_get()
        except tk.TclError:
            text = ""
        root.destroy()
        return {"ok": True, "text": "" if text is None else str(text)}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc)}


def normalize_path(path: str | None) -> tuple[Path | None, str | None]:
    """Expand/resolve a user path. Returns (path, error)."""
    raw = str(path or "").strip()
    if not raw:
        return None, "路径不能为空"
    if any(ord(ch) < 0x20 for ch in raw):
        return None, (
            f"路径包含换行/控制字符（通常是 JSON 转义错误，反斜杠被吃掉）: {raw!r}。"
            "Windows 路径的反斜杠在 JSON 中应写作 \\\\"
        )
    if _DRIVE_RELATIVE_RE.match(raw):
        fixed = raw[:2] + "\\" + raw[2:]
        return None, (
            f"盘符相对路径缺少分隔符: {raw}。"
            f"Windows 绝对路径应写作 {fixed}；在 JSON 参数中反斜杠需双写为 {fixed.replace(chr(92), chr(92) * 2)}"
        )
    if any(ord(ch) < 0x20 for ch in raw):
        return None, (
            f"路径包含换行/控制字符（通常是 JSON 转义错误，反斜杠被吃掉）: {raw!r}。"
            "Windows 路径的反斜杠在 JSON 中应写作 \\\\"
        )
    try:
        p = Path(raw).expanduser()
        # resolve(strict=False) so write can create new files
        p = p.resolve(strict=False)
        return p, None
    except Exception as exc:
        return None, str(exc)


def read_text_file(
    path: Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int = MAX_FILE_READ_BYTES,
) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "content": "", "path": str(path), "error": "文件不存在"}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"ok": False, "content": "", "path": str(path), "error": str(exc)}
    if size > max_bytes:
        return {
            "ok": False,
            "content": "",
            "path": str(path),
            "error": f"文件过大（{size} 字节），上限 {max_bytes} 字节",
        }
    enc = (encoding or "utf-8").strip() or "utf-8"
    try:
        content = path.read_text(encoding=enc)
        return {"ok": True, "content": content, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "content": "", "path": str(path), "error": str(exc)}


def write_text_file(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    append: bool = False,
) -> dict[str, Any]:
    enc = (encoding or "utf-8").strip() or "utf-8"
    text = "" if content is None else str(content)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding=enc, newline="") as f:
            f.write(text)
        return {"ok": True, "content": text if not append else "", "path": str(path)}
    except Exception as exc:
        return {"ok": False, "content": "", "path": str(path), "error": str(exc)}
