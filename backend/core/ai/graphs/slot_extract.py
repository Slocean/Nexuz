"""Deterministic slot extraction from user utterances (LLM-failure fallback).

Only extracts values explicitly present in the text — never invents contacts/apps.
"""

from __future__ import annotations

import re
from typing import Any


def _extract_quoted(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"[「\"'“](.+?)[」\"'”]", text)]


def extract_slots_from_utterance(text: str) -> dict[str, str]:
    """
    Pull known_slots from natural language without LLM.
    Keys may include: window_title, contact, message, run_at, schedule.
    """
    t = (text or "").strip()
    if not t:
        return {}
    slots: dict[str, str] = {}
    lower = t.lower()

    # --- window / app (only if named in utterance) ---
    m = re.search(r"(?:打开|启动|激活|切换到|用)\s*([^\s，,。；;给发送]{1,24})", t)
    if m:
        cand = m.group(1).strip().strip("的")
        if cand and cand not in ("一下", "这个", "那个"):
            slots["window_title"] = cand
    if not slots.get("window_title"):
        for name in ("微信", "QQ", "钉钉", "飞书", "企业微信", "Telegram", "Discord"):
            if name.lower() in lower or name in t:
                slots["window_title"] = name
                break

    # --- message ---
    message = ""
    m = re.search(r"发送(?:一条)?\s*[「\"'“](.+?)[」\"'”]", t)
    if m:
        message = m.group(1).strip()
    if not message:
        m = re.search(r"(?:消息|内容)\s*[「\"'“](.+?)[」\"'”]", t)
        if m:
            message = m.group(1).strip()
    if not message:
        m = re.search(r"(?:发送|发消息|发一条|发给?他?)\s*[：:]\s*(.+)$", t)
        if m:
            message = m.group(1).strip().strip("「」\"'“”")
    if not message:
        m = re.search(r"(?:消息|内容)\s*[：:]\s*(.+)$", t)
        if m:
            message = m.group(1).strip().strip("「」\"'“”")
    if not message:
        for q in _extract_quoted(t):
            if q and len(q) <= 120:
                message = q
                break
    if message:
        slots["message"] = message

    # --- contact / session name ---
    contact = ""
    # 「给文件传输助手给他发送：…」「给张三发送」
    m = re.search(
        r"给\s*(.+?)\s*(?:给他|给她|给它)?\s*(?:发送|发消息|发一条|发：|发:)",
        t,
    )
    if m:
        contact = m.group(1).strip()
    if not contact:
        m = re.search(r"发给\s*([^\s，,「\"'“]{1,40})", t)
        if m:
            contact = m.group(1).strip()
    if not contact:
        m = re.search(r"给\s*([^\s，,「\"'“]{1,40})\s*(?:发|送)", t)
        if m:
            contact = m.group(1).strip()
    # Strip trailing pronouns accidentally captured
    if contact:
        contact = re.sub(r"(他|她|它)$", "", contact).strip()
        for noise in ("发送", "发消息", "消息"):
            if contact.endswith(noise):
                contact = contact[: -len(noise)].strip()
    if contact and contact != slots.get("window_title"):
        slots["contact"] = contact

    # --- schedule ---
    once = any(k in t for k in ("执行一次", "马上", "立刻", "立即", "现在发", "现在就"))
    m = re.search(r"(\d{1,2})\s*[点:：]\s*(\d{0,2})", t)
    if m and any(k in t for k in ("定时", "每天", "点执行", "到点", "分发")):
        hh, mm = m.group(1), m.group(2) or "00"
        slots["run_at"] = f"{int(hh):02d}:{int(mm or 0):02d}"
        slots["schedule"] = "false" if once else "true"
    elif once:
        slots["schedule"] = "false"

    return {k: v for k, v in slots.items() if v}


def merge_slots(
    base: dict[str, str] | None,
    extra: dict[str, str] | None,
    *,
    prefer_extra: bool = False,
) -> dict[str, str]:
    out = {str(k): str(v) for k, v in (base or {}).items() if v}
    for k, v in (extra or {}).items():
        if not v:
            continue
        if prefer_extra or k not in out or not out[k]:
            out[str(k)] = str(v)
    return out


def outline_looks_weak(outline: dict[str, Any] | None) -> bool:
    """True when outline is empty or only a placeholder delay."""
    if not isinstance(outline, dict):
        return True
    steps = [s for s in (outline.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return True
    hints = {str(s.get("block_hint") or "").lower() for s in steps}
    useful = hints - {"", "delay"}
    return not useful
