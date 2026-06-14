# backend/test/test_run_tests_node.py
# 运行：python test/test_run_tests_node.py

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph import nodes
from app.graph.state import FixPilotState
from app.schemas.test_result import TestRunResult


def _fake_result(command: str, passed: bool = True) -> TestRunResult:
    return TestRunResult(
        command=command,
        exit_code=0 if passed else 1,
        passed=passed,
        duration_ms=10,
        error_message=None if passed else f"{command} failed",
    )


def test_run_tests_node_runs_test_lint_typecheck():
    state = FixPilotState(
        repo_path="/tmp/fake-repo",
        test_command="pytest",
        lint_command="ruff check .",
        typecheck_command="mypy .",
        test_results=[],
        project_info={"primary_type": "python"},
    )

    with patch("app.graph.nodes.run_tests_in_docker") as mock_run:
        mock_run.side_effect = lambda repo_path, command, project_type=None, **kw: _fake_result(
            command
        )
        updates = nodes.run_tests_node(state)

    assert updates["current_node"] == "run_tests_node"
    results = updates["test_results"]
    assert len(results) == 3
    assert [r["check_type"] for r in results] == ["test", "lint", "typecheck"]
    assert all(r["passed"] for r in results)
    assert "error_message" not in updates
    print("[OK] test + lint + typecheck 全部执行")


def test_run_tests_node_collects_failures():
    state = FixPilotState(
        repo_path="/tmp/fake-repo",
        test_command="pytest",
        lint_command="ruff check .",
        test_results=[],
        project_info={"primary_type": "python"},
    )

    with patch("app.graph.nodes.run_tests_in_docker") as mock_run:
        mock_run.side_effect = lambda repo_path, command, project_type=None, **kw: _fake_result(
            command,
            passed=command != "ruff check .",
        )
        updates = nodes.run_tests_node(state)

    assert len(updates["test_results"]) == 2
    assert "Lint" in updates["error_message"]
    print("[OK] 失败项汇总到 error_message")


def test_run_tests_node_skips_when_no_commands():
    state = FixPilotState(repo_path="/tmp/fake-repo", test_results=[])
    updates = nodes.run_tests_node(state)
    assert updates.get("test_results") is None
    print("[OK] 无命令时跳过 Docker")


if __name__ == "__main__":
    test_run_tests_node_runs_test_lint_typecheck()
    test_run_tests_node_collects_failures()
    test_run_tests_node_skips_when_no_commands()
    print("\nrun_tests_node 单测全部通过")
