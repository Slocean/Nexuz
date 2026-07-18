"""Shared helpers for system IO blocks (clipboard, files, paths)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Soft cap for file_io read to avoid blowing up UI / context memory.
MAX_FILE_READ_BYTES = 2 * 1024 * 1024


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
