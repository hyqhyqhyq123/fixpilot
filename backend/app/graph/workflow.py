# backend/app/graph/workflow.py
# 作用：组装 LangGraph Workflow，并在审批前中断等待人工操作

import logging
from functools import lru_cache
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.state import FixPilotState

logger = logging.getLogger(__name__)


def _route_after_approval(
    state: FixPilotState,
) -> Literal["planning_node", "edit_code_node", "final_report_node"]:
    approval_status = state.get("approval_status", "pending")
    if approval_status == "rejected":
        return "planning_node"
    if approval_status == "approved":
        return "edit_code_node"
    return "final_report_node"


def _route_after_tests(
    state: FixPilotState,
) -> Literal["diagnose_failure_node", "review_diff_node", "final_report_node"]:
    results = state.get("test_results") or []
    if results and any(not item.get("passed") for item in results):
        return "diagnose_failure_node"
    if state.get("error_message"):
        return "diagnose_failure_node"
    if state.get("edit_history"):
        return "review_diff_node"
    return "final_report_node"


def _route_after_retry(
    state: FixPilotState,
) -> Literal["edit_code_node", "review_diff_node", "final_report_node"]:
    if state.get("retry_decision") == "retry":
        return "edit_code_node"
    if state.get("edit_history"):
        return "review_diff_node"
    return "final_report_node"


def _route_after_review(
    state: FixPilotState,
) -> Literal["pr_writer_node", "final_report_node"]:
    if state.get("review_decision") == "high_risk":
        return "final_report_node"
    results = state.get("test_results") or []
    if results and any(not item.get("passed") for item in results):
        return "final_report_node"
    return "pr_writer_node"


def build_workflow():
    """
    intake → ... → approval → edit ↔ test → diagnose → retry
      → review → pr_writer → report
    """
    graph = StateGraph(FixPilotState)

    graph.add_node("intake_node", nodes.intake_node)
    graph.add_node("clone_repo_node", nodes.clone_repo_node)
    graph.add_node("analyze_repo_node", nodes.analyze_repo_node)
    graph.add_node("classify_issue_node", nodes.classify_issue_node)
    graph.add_node("retrieve_context_node", nodes.retrieve_context_node)
    graph.add_node("planning_node", nodes.planning_node)
    graph.add_node("approval_node", nodes.approval_node)
    graph.add_node("edit_code_node", nodes.edit_code_node)
    graph.add_node("run_tests_node", nodes.run_tests_node)
    graph.add_node("diagnose_failure_node", nodes.diagnose_failure_node)
    graph.add_node("retry_decision_node", nodes.retry_decision_node)
    graph.add_node("review_diff_node", nodes.review_diff_node)
    graph.add_node("pr_writer_node", nodes.pr_writer_node)
    graph.add_node("final_report_node", nodes.final_report_node)

    graph.add_edge(START, "intake_node")
    graph.add_edge("intake_node", "clone_repo_node")
    graph.add_edge("clone_repo_node", "analyze_repo_node")
    graph.add_edge("analyze_repo_node", "classify_issue_node")
    graph.add_edge("classify_issue_node", "retrieve_context_node")
    graph.add_edge("retrieve_context_node", "planning_node")
    graph.add_edge("planning_node", "approval_node")
    graph.add_conditional_edges(
        "approval_node",
        _route_after_approval,
        {
            "planning_node": "planning_node",
            "edit_code_node": "edit_code_node",
            "final_report_node": "final_report_node",
        },
    )
    graph.add_edge("edit_code_node", "run_tests_node")
    graph.add_conditional_edges(
        "run_tests_node",
        _route_after_tests,
        {
            "diagnose_failure_node": "diagnose_failure_node",
            "review_diff_node": "review_diff_node",
            "final_report_node": "final_report_node",
        },
    )
    graph.add_edge("diagnose_failure_node", "retry_decision_node")
    graph.add_conditional_edges(
        "retry_decision_node",
        _route_after_retry,
        {
            "edit_code_node": "edit_code_node",
            "review_diff_node": "review_diff_node",
            "final_report_node": "final_report_node",
        },
    )
    graph.add_conditional_edges(
        "review_diff_node",
        _route_after_review,
        {
            "pr_writer_node": "pr_writer_node",
            "final_report_node": "final_report_node",
        },
    )
    graph.add_edge("pr_writer_node", "final_report_node")
    graph.add_edge("final_report_node", END)

    checkpointer = MemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval_node"],
    )


@lru_cache
def get_workflow_app():
    logger.info("编译 LangGraph Workflow")
    return build_workflow()
