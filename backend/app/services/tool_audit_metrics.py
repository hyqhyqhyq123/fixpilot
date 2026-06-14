# backend/app/services/tool_audit_metrics.py
# 作用：把 tool_calls 审计日志汇总成可量化指标。
#
# 面试里如果被问“Agent 会不会乱调工具”，不能只回答“我做了权限分级”。
# 更好的回答是：每个任务能统计工具调用成功率、高风险调用占比、未知工具数、
# 高风险工具是否都有保护手段，以及平均耗时。

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from app.core.tool_permissions import TOOL_PERMISSION_LEVELS
from app.models.tool_call import PermissionLevel, ToolCall, ToolCallStatus


# 这些高风险工具不是不能用，而是必须说明它们被什么保护住了。
GUARDED_HIGH_RISK_TOOLS: dict[str, str] = {
    "edit_file_tool": "人工审批 + allowed_files 白名单 + 快照回滚",
    "run_tests_tool": "Docker 沙箱 + 超时",
    "run_lint_tool": "Docker 沙箱 + 超时",
    "run_typecheck_tool": "Docker 沙箱 + 超时",
    "create_branch_tool": "显式 GitHub 操作",
    "commit_tool": "显式 GitHub 操作",
    "create_pr_tool": "登录态 + Token + 人工触发",
    "dependency_install_tool": "审批后执行",
    "rollback_retry_tool": "high 权限审计 + 指定 retry_index",
}


@dataclass(frozen=True)
class ToolAuditMetrics:
    total_calls: int
    success_rate: float
    failed_calls: int
    high_risk_calls: int
    high_risk_rate: float
    high_risk_failed_calls: int
    unknown_tool_calls: int
    guarded_high_risk_rate: float
    avg_duration_ms: float | None
    tool_frequency: dict[str, int]
    permission_frequency: dict[str, int]


def summarize_tool_calls(tool_calls: Iterable[ToolCall]) -> ToolAuditMetrics:
    """把一批 ToolCall 记录汇总成安全和稳定性指标。"""

    calls = list(tool_calls)
    total = len(calls)
    if total == 0:
        return ToolAuditMetrics(
            total_calls=0,
            success_rate=1.0,
            failed_calls=0,
            high_risk_calls=0,
            high_risk_rate=0.0,
            high_risk_failed_calls=0,
            unknown_tool_calls=0,
            guarded_high_risk_rate=1.0,
            avg_duration_ms=None,
            tool_frequency={},
            permission_frequency={},
        )

    success_count = sum(1 for item in calls if item.status == ToolCallStatus.SUCCESS)
    failed_calls = total - success_count
    high_risk = [item for item in calls if item.permission_level == PermissionLevel.HIGH]
    guarded_high_risk = [
        item for item in high_risk if item.tool_name in GUARDED_HIGH_RISK_TOOLS
    ]
    durations = [item.duration_ms for item in calls if item.duration_ms is not None]

    return ToolAuditMetrics(
        total_calls=total,
        success_rate=success_count / total,
        failed_calls=failed_calls,
        high_risk_calls=len(high_risk),
        high_risk_rate=len(high_risk) / total,
        high_risk_failed_calls=sum(
            1 for item in high_risk if item.status == ToolCallStatus.FAILED
        ),
        unknown_tool_calls=sum(
            1 for item in calls if item.tool_name not in TOOL_PERMISSION_LEVELS
        ),
        guarded_high_risk_rate=(
            len(guarded_high_risk) / len(high_risk) if high_risk else 1.0
        ),
        avg_duration_ms=mean(durations) if durations else None,
        tool_frequency=dict(Counter(item.tool_name for item in calls)),
        permission_frequency=dict(Counter(item.permission_level.value for item in calls)),
    )


def format_tool_audit_metrics(metrics: ToolAuditMetrics) -> str:
    """稳定格式化一行指标，方便测试、日志和面试展示。"""

    avg_duration = (
        "-" if metrics.avg_duration_ms is None else f"{metrics.avg_duration_ms:.1f}"
    )
    return (
        f"ToolAudit: total={metrics.total_calls}, "
        f"success_rate={metrics.success_rate:.3f}, "
        f"high_risk_rate={metrics.high_risk_rate:.3f}, "
        f"guarded_high_risk_rate={metrics.guarded_high_risk_rate:.3f}, "
        f"unknown_tool_calls={metrics.unknown_tool_calls}, "
        f"avg_duration_ms={avg_duration}"
    )
