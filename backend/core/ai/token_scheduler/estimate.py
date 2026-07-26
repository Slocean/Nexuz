"""Shared token estimate (no tokenizer dependency)."""

from __future__ import annotations

import re


def estimate_tokens(text: str | None) -> int:
    """Conservative token estimate; bias high so we compact before hard-fail."""
    s = text or ""
    if not s:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", s))
    other = max(0, len(s) - cjk)
    return int(cjk / 1.5 + other / 3.5) + 1
