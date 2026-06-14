import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.project_evaluation import (
    evaluate_swebench_file_localization,
    evaluate_swebench_predictions,
    load_swebench_rows,
    render_evaluation_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "swebench_lite_rows_sample.json"


def test_swebench_lite_fixture_is_real_dataset_shape():
    cases = load_swebench_rows(FIXTURE)
    first = cases[0]
    assert len(cases) == 5
    assert first.instance_id == "astropy__astropy-12907"
    assert first.repo == "astropy/astropy"
    assert first.base_commit
    assert first.patch_files == ["astropy/modeling/separable.py"]
    assert first.fail_to_pass
    assert first.pass_to_pass
    print("[OK] SWE-bench Lite fixture 使用真实 rows schema 和 oracle patch/test 字段")


def test_swebench_file_localization_metrics_are_reproducible():
    cases = load_swebench_rows(FIXTURE)
    result = evaluate_swebench_file_localization(cases)

    assert result.dataset_stats.case_count == 5
    assert result.dataset_stats.unique_repos == 1
    assert result.dataset_stats.fail_to_pass_total >= 5
    assert result.baseline_metrics.recall_at_1 == 0.0
    assert result.fixpilot_metrics.recall_at_1 == 1.0
    assert result.metric_delta["recall_at_1"] == 1.0
    print(
        "[OK] SWE-bench Lite 子集文件定位："
        f"baseline Recall@1={result.baseline_metrics.recall_at_1:.3f}, "
        f"FixPilot Recall@1={result.fixpilot_metrics.recall_at_1:.3f}"
    )


def test_swebench_prediction_resolve_rate_adapter():
    cases = load_swebench_rows(FIXTURE)
    predictions = {
        cases[0].instance_id: True,
        cases[1].instance_id: False,
    }
    metrics = evaluate_swebench_predictions(cases, predictions)
    assert metrics["case_count"] == 5.0
    assert metrics["attempted"] == 2.0
    assert metrics["resolved"] == 1.0
    assert metrics["resolve_rate"] == 0.2
    assert metrics["attempted_resolve_rate"] == 0.5
    print("[OK] SWE-bench resolve_rate 适配器可评估官方 harness 运行结果")


def test_project_evaluation_markdown_contains_method_and_results():
    cases = load_swebench_rows(FIXTURE)
    result = evaluate_swebench_file_localization(cases)
    report = render_evaluation_markdown(
        result,
        dataset_path=str(FIXTURE),
        command="python -m pytest backend/test/test_real_issue_rag_benchmark.py -q -s",
        test_result="3 passed",
    )
    assert "真实 SWE-bench Lite rows" in report
    assert "Recall@1" in report
    assert "完整 SWE-bench resolve rate" in report
    print("[OK] 总评估报告模板包含数据源、方法、指标和测试记录")
