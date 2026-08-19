from __future__ import annotations

from backend.core.ai.eval_runner import run_eval_suite


def test_offline_eval_dataset_is_non_empty_and_meets_quality_gate():
    result = run_eval_suite()
    failures = [
        f"{item['id']}: {item['errors']}"
        for item in result["results"]
        if not item["ok"]
    ]
    assert result["total"] >= 10
    assert result["ok"], "\n".join(failures)
