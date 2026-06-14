# backend/test/test_workflow.py
# 作用：LangGraph Workflow 冒烟测试（不调用 LLM / 不访问数据库）
#
# 运行方式（在 backend 目录下）：
#   python test/test_workflow.py

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph import nodes
from app.graph.state import FixPilotState
from app.graph.workflow import build_workflow
from app.schemas.code_retrieval import CodeRetrievalResult


def test_workflow_compiles():
    app = build_workflow()
    node_names = set(app.get_graph().nodes.keys())
    expected = {
        "__start__",
        "__end__",
        "intake_node",
        "clone_repo_node",
        "analyze_repo_node",
        "classify_issue_node",
        "retrieve_context_node",
        "planning_node",
        "approval_node",
        "edit_code_node",
        "run_tests_node",
        "diagnose_failure_node",
        "retry_decision_node",
        "review_diff_node",
        "pr_writer_node",
        "final_report_node",
    }
    missing = expected - node_names
    assert not missing, f"缺少节点：{missing}"
    print("[OK] Workflow 编译成功，节点齐全")


def test_intake_node():
    state = FixPilotState(
        task_id="1",
        repo_url="https://github.com/pallets/flask",
        issue_text="测试 issue 文本足够长",
    )
    updates = nodes.intake_node(state)
    assert updates["current_agent"] == "coordinator"
    assert updates["status"] == "running"
    print("[OK] intake_node 正常")


def test_retrieve_context_node_uses_hybrid_search():
    captured = {}

    def fake_retrieve_code(request):
        captured["search_method"] = request.search_method
        captured["max_files"] = request.max_files
        return CodeRetrievalResult(
            retrieved_files=[],
            search_method=request.search_method,
        )

    state = FixPilotState(
        task_id="1",
        repo_url="https://github.com/pallets/flask",
        repo_path="D:/tmp/fake-repo",
        issue_text="Calling validate_input raises ValueError",
        issue_analysis={"summary": "validation bug"},
    )

    with patch("app.graph.nodes.retrieve_code", fake_retrieve_code):
        updates = nodes.retrieve_context_node(state)

    assert captured["search_method"] == "hybrid"
    assert captured["max_files"] == 8
    assert updates["current_agent"] == "code_retriever"
    assert updates["retrieved_context"] == []
    print("[OK] retrieve_context_node 主链路使用 hybrid 检索")


if __name__ == "__main__":
    test_workflow_compiles()
    test_intake_node()
    test_retrieve_context_node_uses_hybrid_search()
    print("\n全部 Workflow 冒烟测试通过")
