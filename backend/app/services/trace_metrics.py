"""把 AgentStep 时间线汇总成可回答面试问题的指标。

单条 AgentStep 适合展示时间线；汇总指标适合回答：
“这个任务哪里慢、失败在哪个节点、LLM 大概用了多少 token”。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any, Iterable

from app.models.agent_step import StepStatus


@dataclass(frozen=True)
class TraceMetrics:
    total_steps: int
    success_steps: int
    failed_steps: int
    skipped_steps: int
    success_rate: float
    total_latency_ms: int
    avg_latency_ms: float | None
    slowest_node: str | None
    slowest_latency_ms: int | None
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    failed_nodes: list[str]


def _normalize_status(status: StepStatus | str) -> StepStatus:
    if isinstance(status, StepStatus):
        return status
    return StepStatus(status)


def _duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _token_usage(output_summary: Any) -> dict[str, int]:
    if not isinstance(output_summary, dict):
        return {}
    usage = output_summary.get("token_usage")
    if not isinstance(usage, dict):
        return {}
    return {key: value for key, value in usage.items() if isinstance(value, int)}


def summarize_trace_metrics(steps: Iterable[Any]) -> TraceMetrics:
    """根据 AgentStep 或兼容对象计算汇总指标。"""
    items = list(steps)
    total_steps = len(items)
    status_counts = {
        StepStatus.SUCCESS: 0,
        StepStatus.FAILED: 0,
        StepStatus.SKIPPED: 0,
    }
    failed_nodes: list[str] = []
    durations: list[tuple[str, int]] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    for step in items:
        status = _normalize_status(step.status)
        if status in status_counts:
            status_counts[status] += 1
        if status == StepStatus.FAILED:
            failed_nodes.append(step.node_name)

        duration = _duration_ms(
            getattr(step, "started_at", None),
            getattr(step, "ended_at", None),
        )
        if duration is not None:
            durations.append((step.node_name, duration))

        usage = _token_usage(getattr(step, "output_summary", None))
        prompt_tokens += usage.get("prompt_tokens", 0)
        completion_tokens += usage.get("completion_tokens", 0)
        total_tokens += usage.get("total_tokens", 0)

    success_steps = status_counts[StepStatus.SUCCESS]
    failed_steps = status_counts[StepStatus.FAILED]
    skipped_steps = status_counts[StepStatus.SKIPPED]
    completed_steps = success_steps + failed_steps + skipped_steps
    success_rate = 1.0 if total_steps == 0 else success_steps / total_steps

    if durations:
        slowest_node, slowest_latency_ms = max(durations, key=lambda item: item[1])
        total_latency_ms = sum(duration for _node, duration in durations)
        avg_latency_ms = mean(duration for _node, duration in durations)
    else:
        slowest_node = None
        slowest_latency_ms = None
        total_latency_ms = 0
        avg_latency_ms = None

    # completed_steps 变量留在这里，是为了读代码时明确 success_rate 的分母不是它。
    # 面试时要说清楚：这里的成功率按全部 step 算，running 也会拉低成功率。
    _ = completed_steps

    return TraceMetrics(
        total_steps=total_steps,
        success_steps=success_steps,
        failed_steps=failed_steps,
        skipped_steps=skipped_steps,
        success_rate=success_rate,
        total_latency_ms=total_latency_ms,
        avg_latency_ms=avg_latency_ms,
        slowest_node=slowest_node,
        slowest_latency_ms=slowest_latency_ms,
        total_prompt_tokens=prompt_tokens,
        total_completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        failed_nodes=failed_nodes,
    )


def format_trace_metrics(metrics: TraceMetrics) -> str:
    avg_latency = (
        "-" if metrics.avg_latency_ms is None else f"{metrics.avg_latency_ms:.1f}"
    )
    slowest = (
        "-"
        if metrics.slowest_node is None
        else f"{metrics.slowest_node}:{metrics.slowest_latency_ms}ms"
    )
    return (
        f"TraceMetrics: total={metrics.total_steps}, "
        f"success_rate={metrics.success_rate:.3f}, "
        f"failed={metrics.failed_steps}, "
        f"avg_latency_ms={avg_latency}, "
        f"slowest={slowest}, "
        f"total_tokens={metrics.total_tokens}"
    )
