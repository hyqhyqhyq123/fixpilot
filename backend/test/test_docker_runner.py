# 快速验证 Docker Tester（不经过 API）
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.run_tests_tool import run_tests_in_docker

REPO = Path(__file__).resolve().parents[2] / "workspaces" / "task_5" / "click"
CMD = (
    'python -m pytest tests/test_options.py -q --tb=no -x 2>/dev/null '
    '|| python -c "print(\'skip\')"'
)


def _skip_if_docker_unavailable(error_message: str | None) -> None:
    """当前机器没有 Docker 权限时跳过真实 Docker 冒烟。"""

    if not error_message:
        return

    lowered = error_message.lower()
    unavailable_markers = [
        "access is denied",
        "cannot connect",
        "docker_engine",
        "docker daemon",
        "未找到 docker",
        "拉取镜像失败",
    ]
    if any(marker in lowered for marker in unavailable_markers):
        pytest.skip(f"Docker 当前不可用：{error_message}")


def test_echo_in_docker():
    """最小 Docker 冒烟：不依赖 workspace 仓库。"""
    result = run_tests_in_docker(
        repo_path=str(Path(__file__).parent),
        command="echo docker_ok",
        project_type="python",
    )
    _skip_if_docker_unavailable(result.error_message)
    assert result.passed, result.error_message
    assert "docker_ok" in result.stdout
    print("[OK] Docker echo 冒烟通过")


def test_repo_pytest_if_available():
    if not REPO.is_dir():
        print(f"[SKIP] workspace 不存在: {REPO}")
        return
    result = run_tests_in_docker(str(REPO), CMD, project_type="python")
    print("passed:", result.passed)
    print("exit_code:", result.exit_code)
    print("error:", result.error_message)
    if result.stderr:
        print("stderr:", result.stderr[:1000])
    if result.stdout:
        print("stdout:", result.stdout[:500])


def test_run_tests_node_real_docker():
    """run_tests_node 在真实 Docker 中串联 test + lint + typecheck（FR-601/603/604）。"""
    import tempfile

    from app.graph import nodes
    from app.graph.state import FixPilotState

    with tempfile.TemporaryDirectory() as tmp:
        state = FixPilotState(
            repo_path=tmp,
            test_command="echo test_ok",
            lint_command="echo lint_ok",
            typecheck_command="echo type_ok",
            test_results=[],
            project_info={"primary_type": "python"},
        )
        updates = nodes.run_tests_node(state)
        results = updates["test_results"]
        assert len(results) == 3, results
        for result in results:
            _skip_if_docker_unavailable(result.get("error_message"))
        assert all(r["passed"] for r in results), results
        assert [r["check_type"] for r in results] == ["test", "lint", "typecheck"]
        for key in ("command", "exit_code", "passed", "duration_ms"):
            assert key in results[0], results[0]
        print("[OK] run_tests_node 真实 Docker 三检查通过")


if __name__ == "__main__":
    test_echo_in_docker()
    test_run_tests_node_real_docker()
    test_repo_pytest_if_available()
    print("\nDocker Tester 测试完成")
