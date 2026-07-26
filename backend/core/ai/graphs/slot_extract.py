"""Slot merge helpers. Slot values come from the LLM understand stage.

No utterance→task regex routing (that was demo-era IM matching).
"""

from __future__ import annotations

from typing import Any


def extract_slots_from_utterance(text: str) -> dict[str, str]:
    """Intentionally empty: do not keyword-match task types from raw text."""
    del text
    return {}


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
