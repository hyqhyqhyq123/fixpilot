# backend/test/test_reviewer.py
# 运行：python test/test_reviewer.py

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.reviewer import review_diff, review_diff_heuristic
from app.agents.pr_writer import generate_pr_heuristic
from app.graph import nodes
from app.graph.state import FixPilotState


def test_heuristic_unauthorized_file():
    result = review_diff_heuristic(
        allowed_files=["src/a.py"],
        edit_history=[{"file_path": "src/a.py"}, {"file_path": "secret.env"}],
        current_diff="+ password = 'x'",
        issue_text="fix bug",
        plan={"problem_summary": "fix"},
    )
    assert result.has_unauthorized_changes is True
    assert result.risk_level == "high"
    assert result.approval_required is True
    assert any(i.type == "scope_creep" for i in result.issues)
    print("[OK] 计划外文件 → high risk")


def test_heuristic_clean_diff():
    result = review_diff_heuristic(
        allowed_files=["src/a.py"],
        edit_history=[{"file_path": "src/a.py"}],
        current_diff="+ return True",
        issue_text="fix",
        plan={},
    )
    assert result.risk_level == "low"
    assert result.approval_required is False
    print("[OK] 干净 diff → low risk")


def test_review_with_mock_llm():
    fake = """
    {
      "risk_level": "medium",
      "review_comments": ["建议补测试"],
      "issues": [{"type": "missing_test", "message": "缺少测试", "file": null}],
      "has_unauthorized_changes": false,
      "has_dangerous_code": false,
      "has_sensitive_info": false,
      "matches_issue_goal": true,
      "approval_required": false,
      "summary": "整体可接受"
    }
    """
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=fake)

    with patch("app.agents.reviewer.ChatOpenAI", return_value=mock_llm):
        result = review_diff(
            issue_text="fix",
            plan={"problem_summary": "x"},
            allowed_files=["a.py"],
            edit_history=[{"file_path": "a.py"}],
            current_diff="+ pass",
        )
    assert result.risk_level == "medium"
    print("[OK] Reviewer LLM JSON 解析")


def test_review_diff_node_high_risk():
    state = FixPilotState(
        issue_text="fix",
        allowed_files=["a.py"],
        edit_history=[{"file_path": "b.py"}],
        current_diff="+ evil eval(x)",
    )
    with patch("app.graph.nodes.review_diff") as mock_review:
        from app.schemas.review import ReviewResult

        mock_review.return_value = ReviewResult(
            risk_level="high",
            approval_required=True,
            summary="危险",
        )
        updates = nodes.review_diff_node(state)
    assert updates["review_decision"] == "high_risk"
    print("[OK] review_diff_node high_risk 决策")


def test_pr_writer_heuristic():
    pr = generate_pr_heuristic(
        issue_text="修复空输入校验",
        plan={"problem_summary": "空输入应报错"},
        edit_history=[{"file_path": "src/validator.py"}],
        test_results=[{"passed": True, "command": "pytest", "check_type": "test"}],
        review_result={"risk_level": "low", "review_comments": []},
    )
    assert pr.title.startswith("fix:")
    assert pr.commit_message.startswith("fix:")
    assert "validator.py" in pr.changes
    assert "## Commit Message" in pr.full_markdown
    assert pr.commit_message in pr.full_markdown
    assert "## Summary" in pr.full_markdown
    print("[OK] PR Writer 模板生成")


def test_pr_writer_node():
    state = FixPilotState(
        issue_text="fix",
        plan={"problem_summary": "x"},
        edit_history=[{"file_path": "a.py"}],
        current_diff="+ fix",
        test_results=[],
        review_result={"risk_level": "low", "summary": "ok"},
    )
    updates = nodes.pr_writer_node(state)
    assert updates.get("pr_draft")
    assert "## Commit Message" in updates["pr_draft"]
    assert len(updates["pr_draft"]) > 50
    print("[OK] pr_writer_node 写入 pr_draft")


if __name__ == "__main__":
    test_heuristic_unauthorized_file()
    test_heuristic_clean_diff()
    test_review_with_mock_llm()
    test_review_diff_node_high_risk()
    test_pr_writer_heuristic()
    test_pr_writer_node()
    print("\nReviewer / PR Writer 测试全部通过")
