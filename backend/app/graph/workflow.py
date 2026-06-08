# backend/app/graph/workflow.py
# 作用：组装 LangGraph 线性 Workflow，并在审批前中断等待人工操作
#
# interrupt_before 是什么？
# 图执行到 approval_node 之前会暂停，把控制权交还给 API；
# 用户 approve/reject 后，再由 runner 恢复执行。

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
) -> Literal["planning_node", "final_report_node"]:
    """根据审批结果决定下一步。"""
    approval_status = state.get("approval_status", "pending")
    if approval_status == "rejected":
        return "planning_node"
    return "final_report_node"


def build_workflow():
    """
    构建 Phase 2 线性 Workflow：
    intake → clone → analyze → classify → retrieve → plan → [interrupt] approval → report
    """
    graph = StateGraph(FixPilotState)

    graph.add_node("intake_node", nodes.intake_node)
    graph.add_node("clone_repo_node", nodes.clone_repo_node)
    graph.add_node("analyze_repo_node", nodes.analyze_repo_node)
    graph.add_node("classify_issue_node", nodes.classify_issue_node)
    graph.add_node("retrieve_context_node", nodes.retrieve_context_node)
    graph.add_node("planning_node", nodes.planning_node)
    graph.add_node("approval_node", nodes.approval_node)
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
            "final_report_node": "final_report_node",
        },
    )
    graph.add_edge("final_report_node", END)

    checkpointer = MemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval_node"],
    )


@lru_cache
def get_workflow_app():
    """获取单例 Workflow，避免重复编译。"""
    logger.info("编译 LangGraph Workflow")
    return build_workflow()
