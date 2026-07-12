"""Frida Unity UI stable identity helpers."""

from __future__ import annotations

from typing import Any


def validate_stable_id(data: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "缺少 frida_ui 稳定身份"
    path = str(data.get("hierarchy_path") or "").strip()
    if not path:
        return False, "hierarchy_path 为空"
    if ".." in path or path.startswith("/"):
        return False, "非法 hierarchy_path"
    return True, ""


def stable_id_key(data: dict[str, Any]) -> str:
    path = str(data.get("hierarchy_path") or "")
    ctype = str(data.get("component_type") or "")
    sib = int(data.get("sibling_index", 0) or 0)
    return f"{path}|{ctype}|{sib}"


def summarize_stable_id(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    name = str(data.get("display_name") or "").strip()
    path = str(data.get("hierarchy_path") or "").strip()
    btn = ""
    return name or path.split("/")[-1] if path else ""
