# backend/test/test_tool_audit_metrics.py
# 面试向量化实验：统计 Agent 工具调用是否可审计、是否有高风险保护。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.tool_call import PermissionLevel, ToolCall, ToolCallStatus
from app.services.tool_audit_metrics import (
    format_tool_audit_metrics,
    summarize_tool_calls,
)


def _tool(
    name: str,
    permission: PermissionLevel,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
    duration_ms: int = 100,
) -> ToolCall:
    return ToolCall(
        task_id=1,
        tool_name=name,
        permission_level=permission,
        status=status,
        duration_ms=duration_ms,
    )


def test_tool_audit_metrics_summarize_risk_and_unknown_tools():
    metrics = summarize_tool_calls(
        [
            _tool("semantic_search_tool", PermissionLevel.LOW, duration_ms=40),
            _tool("edit_file_tool", PermissionLevel.HIGH, duration_ms=300),
            _tool("run_tests_tool", PermissionLevel.HIGH, ToolCallStatus.FAILED, 1200),
            _tool("experimental_shell_tool", PermissionLevel.HIGH, duration_ms=50),
        ]
    )

    assert metrics.total_calls == 4
    assert metrics.success_rate == 0.75
    assert metrics.failed_calls == 1
    assert metrics.high_risk_calls == 3
    assert metrics.high_risk_rate == 0.75
    assert metrics.high_risk_failed_calls == 1
    assert metrics.unknown_tool_calls == 1
    assert round(metrics.guarded_high_risk_rate, 3) == 0.667
    assert metrics.tool_frequency["run_tests_tool"] == 1
    assert metrics.permission_frequency["high"] == 3
    print(format_tool_audit_metrics(metrics))
    print("[OK] Tool Audit 能量化成功率、高风险调用和未知工具")


def test_empty_tool_audit_metrics_are_safe_defaults():
    metrics = summarize_tool_calls([])

    assert metrics.total_calls == 0
    assert metrics.success_rate == 1.0
    assert metrics.guarded_high_risk_rate == 1.0
    assert metrics.unknown_tool_calls == 0
    print("[OK] 空工具调用默认视为无风险")


if __name__ == "__main__":
    test_tool_audit_metrics_summarize_risk_and_unknown_tools()
    test_empty_tool_audit_metrics_are_safe_defaults()
