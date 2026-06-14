# backend/test/test_failure_diagnoser.py
# 运行：python test/test_failure_diagnoser.py

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.failure_diagnoser import (
    diagnose_failure_heuristic,
    diagnose_test_failure,
)
from app.graph import nodes
from app.graph.state import FixPilotState


def test_heuristic_env_failure():
    results = [
        {
            "command": "pytest",
            "passed": False,
            "exit_code": 1,
            "stderr": "ModuleNotFoundError: No module named 'foo'",
            "stdout": "",
            "check_type": "test",
        }
    ]
    diagnosis = diagnose_failure_heuristic(results, current_diff="+ fix")
    assert diagnosis.is_caused_by_current_patch is False
    assert diagnosis.should_retry is False
    print("[OK] 环境类失败不重试")


def test_heuristic_patch_failure():
    results = [
        {
            "command": "pytest tests/test_x.py",
            "passed": False,
            "exit_code": 1,
            "stderr": "AssertionError: expected 1 got 2",
            "stdout": "",
            "check_type": "test",
        }
    ]
    diagnosis = diagnose_failure_heuristic(results, current_diff="+ def fix()")
    assert diagnosis.is_caused_by_current_patch is True
    assert diagnosis.should_retry is True
    print("[OK] patch 相关失败建议重试")


def test_diagnose_with_mock_llm():
    fake_json = """
    {
      "failure_summary": "断言失败",
      "likely_cause": "返回值错误",
      "is_caused_by_current_patch": true,
      "next_fix_plan": ["修正返回值"],
      "should_retry": true,
      "retry_hints": "看 test_x"
    }
    """
    results = [
        {
            "command": "pytest",
            "passed": False,
            "exit_code": 1,
            "stderr": "AssertionError",
            "stdout": "",
            "check_type": "test",
        }
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=fake_json)

    with patch("app.agents.failure_diagnoser.ChatOpenAI", return_value=mock_llm):
        diagnosis = diagnose_test_failure(
            issue_text="fix bug",
            plan={"problem_summary": "fix"},
            test_results=results,
            current_diff="+ patch",
            retry_count=0,
        )

    assert diagnosis.should_retry is True
    assert diagnosis.failure_summary == "断言失败"
    print("[OK] LLM 诊断 JSON 解析")


def test_retry_decision_node_retry():
    state = FixPilotState(
        failure_analysis={
            "should_retry": True,
            "is_caused_by_current_patch": True,
            "failure_summary": "断言失败",
        },
        retry_count=0,
        max_retries=2,
        error_message="测试未通过",
    )
    updates = nodes.retry_decision_node(state)
    assert updates["retry_decision"] == "retry"
    assert updates["retry_count"] == 1
    assert updates.get("error_message") is None
    print("[OK] retry_decision_node 允许重试")


def test_retry_decision_node_stop_at_max():
    state = FixPilotState(
        failure_analysis={
            "should_retry": True,
            "is_caused_by_current_patch": True,
            "failure_summary": "仍失败",
        },
        retry_count=2,
        max_retries=2,
    )
    updates = nodes.retry_decision_node(state)
    assert updates["retry_decision"] == "stop"
    assert "最大重试" in (updates.get("error_message") or "")
    print("[OK] 达到 max_retries 停止")


def test_retry_decision_node_stop_not_caused_by_patch():
    state = FixPilotState(
        failure_analysis={
            "should_retry": True,
            "is_caused_by_current_patch": False,
            "failure_summary": "Docker 错误",
        },
        retry_count=0,
        max_retries=2,
    )
    updates = nodes.retry_decision_node(state)
    assert updates["retry_decision"] == "stop"
    assert "无关" in (updates.get("error_message") or "")
    print("[OK] 非 patch 导致停止重试")


if __name__ == "__main__":
    test_heuristic_env_failure()
    test_heuristic_patch_failure()
    test_diagnose_with_mock_llm()
    test_retry_decision_node_retry()
    test_retry_decision_node_stop_at_max()
    test_retry_decision_node_stop_not_caused_by_patch()
    print("\nFailure Diagnosis / Retry 测试全部通过")
