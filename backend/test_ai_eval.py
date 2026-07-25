"""AI eval suite gate (Plan1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks
from backend.core.ai.eval_runner import run_eval_suite


@pytest.fixture(scope="module", autouse=True)
def _blocks():
    register_all_blocks()


def test_eval_suite_pass_rate():
    report = run_eval_suite()
    assert report["total"] >= 60
    assert report["pass_rate"] >= 0.85, report
    assert report["ok"] is True
