# backend/app/graph/nodes.py
# 作用：LangGraph 各 Node 的纯业务逻辑（不直接访问数据库）
#
# 设计原则：
# - 每个 Node 只调用已有的 Agent / Tool
# - 返回 State 更新字段，由 workflow_runner 负责写 DB

import logging
from typing import Any

from app.agents.code_retriever import retrieve_code
from app.agents.issue_analyst import analyze_issue
from app.agents.planner import generate_fix_plan
from app.graph.state import FixPilotState
from app.schemas.code_retrieval import CodeRetrievalRequest
from app.schemas.issue_analysis import IssueAnalysisRequest
from app.tools.repo_analysis_tool import (
    detect_project_info,
    get_file_tree_text,
    list_files,
)
from app.tools.repo_clone_tool import clone_repo

logger = logging.getLogger(__name__)


def _project_info_to_context(project_info: dict[str, Any] | None) -> str:
    """把项目分析结果转成 Issue Analyst 可读的仓库背景。"""
    if not project_info:
        return ""
    parts = [
        f"主要语言：{project_info.get('primary_language', '未知')}",
        f"项目类型：{project_info.get('primary_type', '未知')}",
        f"包管理器：{project_info.get('package_manager', '未知')}",
    ]
    frameworks = project_info.get("frameworks") or []
    if frameworks:
        parts.append(f"框架：{', '.join(frameworks)}")
    return "\n".join(parts)


def _extract_allowed_files(plan: dict[str, Any]) -> list[str]:
    """从修改计划中提取允许 Coder 修改的文件列表。"""
    paths: list[str] = []
    for key in ("files_to_modify", "files_to_add"):
        for item in plan.get(key) or []:
            path = item.get("path")
            if path:
                paths.append(path)
    return paths


def intake_node(state: FixPilotState) -> dict[str, Any]:
    """初始化任务上下文。"""
    logger.info(f"intake_node：task_id={state.get('task_id')}")
    return {
        "current_agent": "coordinator",
        "current_node": "intake_node",
        "status": "running",
        "approval_status": state.get("approval_status") or "pending",
        "retrieved_context": state.get("retrieved_context") or [],
        "edit_history": state.get("edit_history") or [],
        "test_results": state.get("test_results") or [],
        "allowed_files": state.get("allowed_files") or [],
    }


def clone_repo_node(state: FixPilotState) -> dict[str, Any]:
    """克隆 GitHub 仓库到任务 workspace。"""
    task_id = int(state["task_id"])
    repo_url = state["repo_url"]
    logger.info(f"clone_repo_node：task_id={task_id}, repo={repo_url}")

    result = clone_repo(task_id=task_id, repo_url=repo_url)
    if not result["success"]:
        return {
            "current_agent": "repository_analyst",
            "current_node": "clone_repo_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": result.get("error") or result.get("message"),
        }

    return {
        "current_agent": "repository_analyst",
        "current_node": "clone_repo_node",
        "repo_path": result["repo_path"],
        "status": "running",
    }


def analyze_repo_node(state: FixPilotState) -> dict[str, Any]:
    """分析仓库结构、语言、测试命令等。"""
    repo_path = state.get("repo_path")
    if not repo_path:
        return {
            "current_node": "analyze_repo_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": "repo_path 为空，无法分析仓库",
        }

    logger.info(f"analyze_repo_node：repo_path={repo_path}")
    project_info = detect_project_info(repo_path)
    analysis = list_files(repo_path)
    file_tree_summary = get_file_tree_text(analysis)

    updates: dict[str, Any] = {
        "current_agent": "repository_analyst",
        "current_node": "analyze_repo_node",
        "project_info": project_info.model_dump(),
        "file_tree_summary": file_tree_summary,
        "status": "running",
    }

    # 用户未指定时，用仓库分析结果补全测试 / lint 命令
    if not state.get("test_command") and project_info.test_command:
        updates["test_command"] = project_info.test_command
    if not state.get("lint_command") and project_info.lint_command:
        updates["lint_command"] = project_info.lint_command
    if not state.get("typecheck_command") and project_info.typecheck_command:
        updates["typecheck_command"] = project_info.typecheck_command

    return updates


def classify_issue_node(state: FixPilotState) -> dict[str, Any]:
    """Issue Analyst：结构化分析 issue。"""
    logger.info(f"classify_issue_node：task_id={state.get('task_id')}")
    request = IssueAnalysisRequest(
        issue_text=state["issue_text"],
        repo_context=_project_info_to_context(state.get("project_info")),
    )
    analysis = analyze_issue(request)
    return {
        "current_agent": "issue_analyst",
        "current_node": "classify_issue_node",
        "issue_analysis": analysis.model_dump(),
        "status": "running",
    }


def retrieve_context_node(state: FixPilotState) -> dict[str, Any]:
    """Code Retriever：检索与 issue 相关的代码片段。"""
    repo_path = state.get("repo_path")
    if not repo_path:
        return {
            "current_node": "retrieve_context_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": "repo_path 为空，无法检索代码",
        }

    issue_analysis = state.get("issue_analysis") or {}
    summary = issue_analysis.get("summary", "")

    logger.info(f"retrieve_context_node：repo_path={repo_path}")
    request = CodeRetrievalRequest(
        repo_path=repo_path,
        query_text=state["issue_text"],
        issue_summary=summary,
        search_method="semantic",
        max_files=8,
    )
    result = retrieve_code(request)
    retrieved_context = [item.model_dump() for item in result.retrieved_files]

    return {
        "current_agent": "code_retriever",
        "current_node": "retrieve_context_node",
        "retrieved_context": retrieved_context,
        "status": "running",
    }


def planning_node(state: FixPilotState) -> dict[str, Any]:
    """Planner：生成修改计划。"""
    logger.info(f"planning_node：task_id={state.get('task_id')}")

    feedback_section = ""
    if state.get("user_feedback"):
        feedback_section = f"\n\n用户拒绝原因：{state['user_feedback']}"

    plan = generate_fix_plan(
        issue_text=state["issue_text"] + feedback_section,
        issue_analysis=state.get("issue_analysis"),
        retrieved_result={"retrieved_files": state.get("retrieved_context") or []},
        repo_analysis=state.get("project_info"),
    )
    plan_dict = plan.model_dump()

    return {
        "current_agent": "planner",
        "current_node": "planning_node",
        "plan": plan_dict,
        "allowed_files": _extract_allowed_files(plan_dict),
        "approval_status": "pending",
        "status": "waiting_approval",
    }


def approval_node(state: FixPilotState) -> dict[str, Any]:
    """审批节点：实际审批结果由 API 写入 State 后恢复执行。"""
    logger.info(
        f"approval_node：task_id={state.get('task_id')}, "
        f"approval_status={state.get('approval_status')}"
    )
    return {
        "current_agent": "coordinator",
        "current_node": "approval_node",
    }


def final_report_node(state: FixPilotState) -> dict[str, Any]:
    """生成阶段性报告（Phase 2 在审批后结束，Coder 在 Phase 3 接入）。"""
    approval_status = state.get("approval_status", "pending")
    plan = state.get("plan") or {}
    error_message = state.get("error_message")

    if error_message:
        report = f"任务执行失败：{error_message}"
        final_status = "failed"
        status = "failed"
    elif approval_status == "cancelled":
        report = "任务已被用户取消。"
        final_status = "cancelled"
        status = "cancelled"
    elif approval_status == "approved":
        report = (
            "修改计划已批准。\n"
            f"- 问题摘要：{plan.get('problem_summary', '无')}\n"
            f"- 计划修改文件数：{len(plan.get('files_to_modify', []))}\n"
            f"- 计划新增文件数：{len(plan.get('files_to_add', []))}\n"
            "Coder Agent 将在 Phase 3 根据本计划修改代码。"
        )
        final_status = "plan_approved"
        status = "running"
    elif approval_status == "rejected":
        report = "修改计划被拒绝，已根据用户反馈重新生成计划，请再次审批。"
        final_status = "waiting_approval"
        status = "waiting_approval"
    else:
        report = "任务已暂停，等待人工审批修改计划。"
        final_status = "waiting_approval"
        status = "waiting_approval"

    return {
        "current_agent": "coordinator",
        "current_node": "final_report_node",
        "final_report": report,
        "final_status": final_status,
        "status": status,
    }
