from __future__ import annotations

from backend.core.ai.eval_runner import run_eval_suite, run_raw_eval_suite


def test_offline_eval_dataset_is_non_empty_and_meets_quality_gate():
    compile_result = run_eval_suite()
    raw_result = run_raw_eval_suite()
    failures = [f"{item['id']}: {item['errors']}" for item in compile_result["results"] if not item["ok"]]
    failures += [f"{item['id']}: {item['errors']}" for item in raw_result["results"] if not item["ok"]]
    total = compile_result["total"] + raw_result["total"]
    assert total >= 50, f"评测用例不足（两层合计）: {total}"
    assert compile_result["total"] >= 35, f"compile 层用例不足: {compile_result['total']}"
    assert compile_result["ok"], "\n".join(failures)


def test_raw_layer_records_normalized_and_meets_quality_gate():
    """原始层：脏 LLM 输出（别名/裸参数/未知 op）归一化回归。"""
    result = run_raw_eval_suite()
    failures = [
        f"{item['id']}: {item['errors']}"
        for item in result["results"]
        if not item["ok"]
    ]
    assert result["total"] >= 15, f"raw 层用例不足: {result['total']}"
    assert result["ok"], "\n".join(failures)
    # 归一化必须产出闭集 op（别名收敛生效的直接证据）
    ops = {op for item in result["results"] for op in item["ir_ops"]}
    assert ops <= {"activate", "ocr_click", "type", "key", "wait", "wait_text",
                   "schedule", "find_image_click", "color_click", "loop",
                   "if_text", "try_catch"}


def test_raw_layer_model_grouping():
    """按模型分组跑分：只统计标注了该模型的用例，共享用例始终纳入。"""
    all_result = run_raw_eval_suite()
    assert all_result["total"] >= 15
    assert "<shared>" in all_result["by_model"]  # 未标注 models 的用例

    grouped = run_raw_eval_suite(model="qwen2.5-7b-instruct")
    assert grouped["model"] == "qwen2.5-7b-instruct"
    assert grouped["total"] >= 1
    assert grouped["total"] < all_result["total"]  # 分组是全量的真子集
    bucket = grouped["by_model"].get("qwen2.5-7b-instruct")
    assert bucket is not None and bucket["total"] >= 1
