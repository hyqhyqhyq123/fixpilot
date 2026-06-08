# backend/test/test_workflow.py
# 作用：LangGraph Workflow 冒烟测试（不调用 LLM / 不访问数据库）
#
# 运行方式（在 backend 目录下）：
#   python test/test_workflow.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph import nodes
from app.graph.state import FixPilotState
from app.graph.workflow import build_workflow


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


if __name__ == "__main__":
    test_workflow_compiles()
    test_intake_node()
    print("\n全部 Workflow 冒烟测试通过")
