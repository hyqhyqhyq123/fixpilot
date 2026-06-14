# backend/test/test_coder_test_generation.py
# FR-503：bug fix 场景下优先新增或更新测试。

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.coder import apply_approved_plan
from app.agents.planner import _ensure_regression_test_in_plan
from app.schemas.plan import FixPlan, PlannedFileChange
from app.tools.repo_analysis_tool import detect_project_info


def _base_plan() -> FixPlan:
    return FixPlan(
        problem_summary="空输入会触发错误",
        root_cause_hypothesis="validator 没有处理空输入",
        files_to_modify=[
            PlannedFileChange(
                path="src/validator.py",
                reason="修复输入校验",
                planned_changes=["为空输入返回明确错误"],
            )
        ],
        files_to_add=[],
        test_plan=["运行 pytest"],
        risk_analysis="低风险",
    )


def test_repo_analysis_detects_test_directories():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (repo / "tests").mkdir()

        info = detect_project_info(str(repo))

        assert info.test_directories == ["tests"]
        assert info.test_command == "pytest"
        print("[OK] Repository Analyst 能识别测试目录")


def test_planner_adds_regression_test_file_for_bugfix():
    plan = _ensure_regression_test_in_plan(
        _base_plan(),
        issue_analysis={"issue_type": "bug"},
        repo_analysis={
            "primary_type": "python",
            "test_directories": ["tests"],
            "test_command": "pytest",
        },
    )

    added_paths = [item.path for item in plan.files_to_add]
    assert "tests/test_validator.py" in added_paths
    assert any("回归测试" in step for step in plan.test_plan)
    print("[OK] Planner 会把回归测试文件写入计划")


def test_coder_rejects_missing_planned_test_without_note():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "validator.py").write_text("def validate(x):\n    return x\n", encoding="utf-8")

        plan = _ensure_regression_test_in_plan(
            _base_plan(),
            issue_analysis={"issue_type": "bug"},
            repo_analysis={"primary_type": "python", "test_directories": ["tests"]},
        ).model_dump()

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            def invoke(self, messages):
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "edits": [
                                {
                                    "path": "src/validator.py",
                                    "content": "def validate(x):\n    return x or ''\n",
                                    "is_new_file": False,
                                }
                            ],
                            "test_note": None,
                        }
                    )
                )

        with patch("app.agents.coder.ChatOpenAI", FakeLLM):
            result = apply_approved_plan(
                repo_path=str(repo),
                issue_text="空输入时返回清晰错误",
                plan=plan,
                allowed_files=["src/validator.py", "tests/test_validator.py"],
            )

        assert not result.success
        assert "测试文件" in (result.error_message or "")
        assert (repo / "src" / "validator.py").read_text(encoding="utf-8") == "def validate(x):\n    return x\n"
        print("[OK] Coder 不会无说明跳过计划中的测试文件")


def test_coder_allows_missing_test_when_note_is_present():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "validator.py").write_text("def validate(x):\n    return x\n", encoding="utf-8")

        plan = _ensure_regression_test_in_plan(
            _base_plan(),
            issue_analysis={"issue_type": "bug"},
            repo_analysis={"primary_type": "python", "test_directories": ["tests"]},
        ).model_dump()

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            def invoke(self, messages):
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "edits": [
                                {
                                    "path": "src/validator.py",
                                    "content": "def validate(x):\n    return x or ''\n",
                                    "is_new_file": False,
                                }
                            ],
                            "test_note": "现有测试框架缺少可复用 fixture，先说明原因。",
                        }
                    )
                )

        with patch("app.agents.coder.ChatOpenAI", FakeLLM):
            result = apply_approved_plan(
                repo_path=str(repo),
                issue_text="空输入时返回清晰错误",
                plan=plan,
                allowed_files=["src/validator.py", "tests/test_validator.py"],
            )

        assert result.success
        assert result.test_note
        assert (repo / "src" / "validator.py").read_text(encoding="utf-8") == "def validate(x):\n    return x or ''\n"
        print("[OK] Coder 未补测试时必须留下 test_note")


if __name__ == "__main__":
    test_repo_analysis_detects_test_directories()
    test_planner_adds_regression_test_file_for_bugfix()
    test_coder_rejects_missing_planned_test_without_note()
    test_coder_allows_missing_test_when_note_is_present()
    print("\nFR-503 新增测试单测全部通过")
