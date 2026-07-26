"""ContextCompiler packing tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.ai.token_scheduler.compiler import (
    ContextLayer,
    compile_layers,
    distill_tool_result,
)
from backend.core.ai.token_scheduler.estimate import estimate_tokens


def test_distill_tool_result_keeps_head_and_tail():
    fat = "HEAD_MARKER " + ("x" * 5000) + " TAIL_MARKER"
    out = distill_tool_result(fat, max_tokens=120)
    assert "HEAD_MARKER" in out
    assert "TAIL_MARKER" in out
    assert estimate_tokens(out) < estimate_tokens(fat)


def test_compile_non_compressible_survives():
    packed = compile_layers(
        [
            ContextLayer("task", 0, "CRITICAL_SLOT=contact", compressible=False),
            ContextLayer("long", 5, "pad " * 2000, compressible=True),
        ],
        budget_tokens=60,
    )
    assert "CRITICAL_SLOT=contact" in packed
