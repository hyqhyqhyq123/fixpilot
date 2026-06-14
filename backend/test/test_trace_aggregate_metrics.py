import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.agent_step import StepStatus
from app.services.trace_metrics import format_trace_metrics, summarize_trace_metrics


def _step(
    node_name: str,
    status: StepStatus,
    duration_ms: int | None,
    token_usage: dict[str, int] | None = None,
) -> SimpleNamespace:
    started_at = datetime.now(timezone.utc)
    ended_at = (
        None
        if duration_ms is None
        else started_at + timedelta(milliseconds=duration_ms)
    )
    output_summary = {}
    if token_usage:
        output_summary["token_usage"] = token_usage
    return SimpleNamespace(
        node_name=node_name,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        output_summary=output_summary,
    )


def test_trace_metrics_summarize_latency_failure_and_tokens():
    metrics = summarize_trace_metrics(
        [
            _step(
                "classify_issue_node",
                StepStatus.SUCCESS,
                120,
                {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
            ),
            _step(
                "planning_node",
                StepStatus.SUCCESS,
                340,
                {"prompt_tokens": 200, "completion_tokens": 60, "total_tokens": 260},
            ),
            _step("run_tests_node", StepStatus.FAILED, 90),
            _step("diagnose_failure_node", StepStatus.RUNNING, None),
        ]
    )

    assert metrics.total_steps == 4
    assert metrics.success_steps == 2
    assert metrics.failed_steps == 1
    assert metrics.success_rate == 0.5
    assert metrics.total_latency_ms == 550
    assert round(metrics.avg_latency_ms or 0, 1) == 183.3
    assert metrics.slowest_node == "planning_node"
    assert metrics.slowest_latency_ms == 340
    assert metrics.failed_nodes == ["run_tests_node"]
    assert metrics.total_prompt_tokens == 280
    assert metrics.total_completion_tokens == 80
    assert metrics.total_tokens == 360

    print(format_trace_metrics(metrics))
    print("[OK] Trace 汇总能量化成功率、耗时、失败节点和 token")


def test_empty_trace_metrics_are_safe_defaults():
    metrics = summarize_trace_metrics([])
    assert metrics.total_steps == 0
    assert metrics.success_rate == 1.0
    assert metrics.avg_latency_ms is None
    assert metrics.slowest_node is None
    assert metrics.total_tokens == 0
    assert metrics.failed_nodes == []
    print("[OK] 空 Trace 汇总默认视为无失败、无耗时、无 token")
