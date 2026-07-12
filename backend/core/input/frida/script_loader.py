"""Load Frida JS sources from disk."""

from __future__ import annotations

from pathlib import Path


def script_dir() -> Path:
    return Path(__file__).resolve().parent / "scripts"


def load_unity_ui_click_script() -> str:
    path = script_dir() / "unity_ui_click.js"
    if not path.exists():
        raise FileNotFoundError(f"Frida 脚本不存在: {path}")
    return path.read_text(encoding="utf-8")
