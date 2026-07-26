"""ContextCompiler — priority packing with semantic degrade (not tail-chop only)."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.ai.token_scheduler.estimate import estimate_tokens


@dataclass
class ContextLayer:
    """One packable context block. Lower priority number = more important."""

    name: str
    priority: int
    content: str
    compressible: bool = True


def _shrink_text(text: str, keep_ratio: float) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    keep = max(40, int(len(s) * keep_ratio))
    if len(s) <= keep:
        return s
    # Prefer head (task facts) over tail
    return s[:keep].rstrip() + "\n…(compressed)"


def compile_layers(layers: list[ContextLayer], budget_tokens: int) -> str:
    """
    Pack layers by priority into budget_tokens.
    Non-compressible layers always kept (may still truncate if absurdly large).
    Compressible layers degrade: full → 50% → 25% → drop.
    """
    limit = max(64, int(budget_tokens))
    ordered = sorted(layers or [], key=lambda x: (x.priority, x.name))
    # Start with all content
    active: list[ContextLayer] = [
        ContextLayer(x.name, x.priority, (x.content or "").strip(), x.compressible)
        for x in ordered
        if (x.content or "").strip()
    ]

    def render(items: list[ContextLayer]) -> str:
        parts = []
        for it in items:
            parts.append(f"[{it.name}]\n{it.content}")
        return "\n\n".join(parts)

    text = render(active)
    if estimate_tokens(text) <= limit:
        return text

    # Progressive compress compressible layers from lowest priority (highest number)
    for ratio in (0.5, 0.25, 0.1):
        for i in range(len(active) - 1, -1, -1):
            if not active[i].compressible:
                continue
            active[i] = ContextLayer(
                active[i].name,
                active[i].priority,
                _shrink_text(active[i].content, ratio),
                True,
            )
            text = render(active)
            if estimate_tokens(text) <= limit:
                return text

    # Drop compressible from lowest priority
    while active and estimate_tokens(render(active)) > limit:
        drop_idx = None
        for i in range(len(active) - 1, -1, -1):
            if active[i].compressible:
                drop_idx = i
                break
        if drop_idx is None:
            break
        active.pop(drop_idx)

    text = render(active)
    if estimate_tokens(text) <= limit:
        return text

    # Last resort: hard trim rendered blob (keeps head)
    lo, hi = 0, len(text)
    best = text[: max(80, len(text) // 4)]
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid]
        if estimate_tokens(cand) <= limit:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best.rstrip() + "\n…(truncated)"


def distill_tool_result(text: str, *, max_tokens: int = 400) -> str:
    """Force-extract tool returns before they enter the packer."""
    s = (text or "").strip()
    if not s:
        return ""
    if estimate_tokens(s) <= max_tokens:
        return s
    # Keep first + last slice (errors often at end)
    head_budget = max(80, max_tokens * 2 // 3)
    # char approx
    head_chars = head_budget * 3
    tail_chars = max(80, (max_tokens // 3) * 3)
    if len(s) <= head_chars + tail_chars:
        return _shrink_text(s, 0.5)
    return s[:head_chars].rstrip() + "\n…\n" + s[-tail_chars:].lstrip()
