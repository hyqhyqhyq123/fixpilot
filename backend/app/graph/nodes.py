# backend/app/graph/nodes.py
# 作用：LangGraph 各 Node 的纯业务逻辑（不直接访问数据库）
#
# 设计原则：
# - 每个 Node 只调用已有的 Agent / Tool
# - 返回 State 更新字段，由 workflow_runner 负责写 DB

import logging
from typing import Any

from app.agents.code_retriever import retrieve_code
from app.agents.coder import apply_approved_plan
from app.agents.failure_diagnoser import diagnose_test_failure
from app.agents.issue_analyst import analyze_issue
from app.agents.planner import generate_fix_plan
from app.agents.pr_writer import generate_pr_description
from app.agents.repository_analyst import analyze_repository, clone_repository
from app.agents.reviewer import review_diff
from app.tools.run_tests_tool import run_tests_in_docker
from app.services.retrieval_sufficiency import assess_retrieval_sufficiency
from app.graph.state import FixPilotState
from app.schemas.code_retrieval import CodeRetrievalRequest
from app.schemas.issue_analysis import IssueAnalysisRequest

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

    result = clone_repository(task_id=task_id, repo_url=repo_url)
    if not result.success or not result.repo_path:
        return {
            "current_agent": "repository_analyst",
            "current_node": "clone_repo_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": result.error or result.message,
        }

    return {
        "current_agent": "repository_analyst",
        "current_node": "clone_repo_node",
        "repo_path": result.repo_path,
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
    analysis = analyze_repository(repo_path)
    project_info = analysis.project_info

    updates: dict[str, Any] = {
        "current_agent": "repository_analyst",
        "current_node": "analyze_repo_node",
        "project_info": project_info.model_dump(),
        "file_tree_summary": analysis.file_tree_summary,
        "status": "running",
    }

    # 用户未指定时，用仓库分析结果补全测试 / lint 命令
    if not state.get("test_command") and analysis.test_command:
        updates["test_command"] = analysis.test_command
    if not state.get("lint_command") and analysis.lint_command:
        updates["lint_command"] = analysis.lint_command
    if not state.get("typecheck_command") and analysis.typecheck_command:
        updates["typecheck_command"] = analysis.typecheck_command

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
        # 主链路使用 hybrid：语义检索负责“意思相近”，BM25/keyword 负责精确符号。
        # 这样可以减少只靠向量检索漏掉函数名、异常名、文件路径的概率。
        search_method="hybrid",
        max_files=8,
    )
    result = retrieve_code(request)
    retrieved_context = [item.model_dump() for item in result.retrieved_files]
    retrieval_quality = assess_retrieval_sufficiency(result.retrieved_files).model_dump()

    return {
        "current_agent": "code_retriever",
        "current_node": "retrieve_context_node",
        "retrieved_context": retrieved_context,
        "retrieval_quality": retrieval_quality,
        "status": "running",
    }


def planning_node(state: FixPilotState) -> dict[str, Any]:
    """Planner：生成修改计划。"""
    logger.info(f"planning_node：task_id={state.get('task_id')}")

    feedback_section = ""
    if state.get("user_feedback"):
        feedback_section = f"\n\n用户拒绝原因：{state['user_feedback']}"

    repo_analysis = dict(state.get("project_info") or {})
    if state.get("file_tree_summary"):
        repo_analysis["file_tree"] = state["file_tree_summary"]

    plan = generate_fix_plan(
        issue_text=state["issue_text"] + feedback_section,
        issue_analysis=state.get("issue_analysis"),
        retrieved_result={
            "retrieved_files": state.get("retrieved_context") or [],
            "retrieval_quality": state.get("retrieval_quality"),
        },
        repo_analysis=repo_analysis,
    )
    plan_dict = plan.model_dump()

    return {
        "current_agent": "planner",
        "current_node": "planning_node",
        "plan": plan_dict,
        "allowed_files": _extract_allowed_files(plan_dict),
        "approval_status": "pending",
        "pending_approval_type": "plan",
        "status": "waiting_approval",
    }


def edit_code_node(state: FixPilotState) -> dict[str, Any]:
    """Coder：根据已审批计划修改代码。"""
    repo_path = state.get("repo_path")
    plan = state.get("plan")
    allowed_files = state.get("allowed_files") or []

    if not repo_path or not plan:
        return {
            "current_node": "edit_code_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": "缺少 repo_path 或 plan，无法执行 Coder",
        }

    if not allowed_files:
        return {
            "current_node": "edit_code_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": "allowed_files 为空，无法执行 Coder",
        }

    logger.info(f"edit_code_node：task_id={state.get('task_id')}")
    result = apply_approved_plan(
        repo_path=repo_path,
        issue_text=state["issue_text"],
        plan=plan,
        allowed_files=allowed_files,
        retry_index=state.get("retry_count", 0),
        failure_analysis=state.get("failure_analysis") if state.get("retry_count", 0) > 0 else None,
    )

    if not result.success:
        return {
            "current_agent": "coder",
            "current_node": "edit_code_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": result.error_message,
        }

    edit_history = list(state.get("edit_history") or [])
    edit_history.extend(result.edit_records)

    return {
        "current_agent": "coder",
        "current_node": "edit_code_node",
        "edit_history": edit_history,
        "current_diff": result.combined_diff,
        "test_note": result.test_note,
        "status": "running",
    }


def _collect_docker_checks(state: FixPilotState) -> list[tuple[str, str]]:
    """收集要在 Docker 中执行的检查项（测试 / lint / typecheck）。"""
    checks: list[tuple[str, str]] = []
    if state.get("test_command"):
        checks.append(("test", state["test_command"]))
    if state.get("lint_command"):
        checks.append(("lint", state["lint_command"]))
    if state.get("typecheck_command"):
        checks.append(("typecheck", state["typecheck_command"]))
    return checks


def run_tests_node(state: FixPilotState) -> dict[str, Any]:
    """Tester：在 Docker 沙箱中运行测试、lint 和 typecheck（FR-601 / FR-603 / FR-604）。"""
    repo_path = state.get("repo_path")

    if not repo_path:
        return {
            "current_node": "run_tests_node",
            "status": "failed",
            "final_status": "failed",
            "error_message": "repo_path 为空，无法运行测试",
        }

    checks = _collect_docker_checks(state)
    if not checks:
        logger.warning("未配置 test/lint/typecheck 命令，跳过 Docker 检查")
        return {
            "current_agent": "tester",
            "current_node": "run_tests_node",
            "status": "running",
        }

    project_info = state.get("project_info") or {}
    project_type = project_info.get("primary_type")

    test_results = list(state.get("test_results") or [])
    failed_checks: list[str] = []

    for check_type, command in checks:
        logger.info(f"run_tests_node：{check_type} cmd={command}")
        test_result = run_tests_in_docker(
            repo_path=repo_path,
            command=command,
            project_type=project_type,
        )
        record = test_result.model_dump()
        record["check_type"] = check_type
        record["retry_index"] = state.get("retry_count", 0)
        test_results.append(record)

        if not test_result.passed:
            label = {"test": "测试", "lint": "Lint", "typecheck": "类型检查"}.get(
                check_type, check_type
            )
            detail = test_result.error_message or f"{label}未通过"
            failed_checks.append(f"{label}（{command}）：{detail}")

    updates: dict[str, Any] = {
        "current_agent": "tester",
        "current_node": "run_tests_node",
        "test_results": test_results,
        "status": "running",
    }

    if failed_checks:
        updates["error_message"] = "；".join(failed_checks)

    return updates


def _tests_all_passed(state: FixPilotState) -> bool:
    results = state.get("test_results") or []
    if not results:
        return True
    return all(item.get("passed") for item in results)


def diagnose_failure_node(state: FixPilotState) -> dict[str, Any]:
    """Failure Diagnosis：分析测试/lint/typecheck 失败原因（FR-701）。"""
    test_results = state.get("test_results") or []
    if _tests_all_passed(state):
        return {
            "current_agent": "failure_diagnoser",
            "current_node": "diagnose_failure_node",
            "status": "running",
        }

    logger.info(f"diagnose_failure_node：task_id={state.get('task_id')}")
    diagnosis = diagnose_test_failure(
        issue_text=state["issue_text"],
        plan=state.get("plan"),
        test_results=test_results,
        current_diff=state.get("current_diff"),
        retry_count=state.get("retry_count", 0),
    )
    return {
        "current_agent": "failure_diagnoser",
        "current_node": "diagnose_failure_node",
        "failure_analysis": diagnosis.model_dump(),
        "status": "running",
    }


def retry_decision_node(state: FixPilotState) -> dict[str, Any]:
    """
    判断是否回到 Coder 重试（FR-702）。

    写入 retry_decision：retry | stop，供 workflow_runner 分支。
    """
    analysis = state.get("failure_analysis") or {}
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    should_retry = (
        analysis.get("should_retry", False)
        and analysis.get("is_caused_by_current_patch", False)
        and retry_count < max_retries
    )

    updates: dict[str, Any] = {
        "current_agent": "coordinator",
        "current_node": "retry_decision_node",
        "retry_decision": "retry" if should_retry else "stop",
        "status": "running",
    }

    if should_retry:
        updates["retry_count"] = retry_count + 1
        updates["error_message"] = None
        logger.info(f"retry_decision_node：将重试，retry_count → {retry_count + 1}")
    else:
        reason = analysis.get("failure_summary") or state.get("error_message") or "测试未通过"
        if not analysis.get("is_caused_by_current_patch"):
            reason = f"失败与当前 patch 无关，停止重试：{reason}"
        elif retry_count >= max_retries:
            reason = f"已达最大重试次数（{max_retries}）：{reason}"
        elif not analysis.get("should_retry"):
            reason = f"诊断建议停止重试：{reason}"
        updates["error_message"] = reason
        logger.info(f"retry_decision_node：停止重试 — {reason}")

    return updates


def review_diff_node(state: FixPilotState) -> dict[str, Any]:
    """Reviewer：审查 diff 与修改范围（FR-801 / FR-802）。"""
    edit_history = state.get("edit_history") or []
    if not edit_history:
        return {
            "current_agent": "reviewer",
            "current_node": "review_diff_node",
            "status": "running",
        }

    logger.info(f"review_diff_node：task_id={state.get('task_id')}")
    result = review_diff(
        issue_text=state["issue_text"],
        plan=state.get("plan"),
        allowed_files=state.get("allowed_files") or [],
        edit_history=edit_history,
        current_diff=state.get("current_diff"),
        test_results=state.get("test_results"),
    )
    updates: dict[str, Any] = {
        "current_agent": "reviewer",
        "current_node": "review_diff_node",
        "review_result": result.model_dump(),
        "status": "running",
    }
    if result.approval_required:
        updates["review_decision"] = "high_risk"
        updates["pending_approval_type"] = "diff_review"
    else:
        updates["review_decision"] = "proceed"
    return updates


def pr_writer_node(state: FixPilotState) -> dict[str, Any]:
    """PR Writer：生成 PR 文案（FR-901）。"""
    logger.info(f"pr_writer_node：task_id={state.get('task_id')}")
    pr = generate_pr_description(
        issue_text=state["issue_text"],
        plan=state.get("plan"),
        edit_history=state.get("edit_history") or [],
        current_diff=state.get("current_diff"),
        test_results=state.get("test_results"),
        review_result=state.get("review_result"),
    )
    return {
        "current_agent": "pr_writer",
        "current_node": "pr_writer_node",
        "pr_draft": pr.full_markdown,
        "status": "running",
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

    if approval_status == "cancelled":
        report = "任务已被用户取消。"
        final_status = "cancelled"
        status = "cancelled"
    elif approval_status == "approved":
        edit_count = len(state.get("edit_history") or [])
        test_results = state.get("test_results") or []
        check_labels = {"test": "测试", "lint": "Lint", "typecheck": "类型检查"}
        check_lines: list[str] = []
        for item in test_results:
            label = check_labels.get(item.get("check_type", "test"), "检查")
            status_text = "通过" if item.get("passed") else "失败"
            check_lines.append(f"{label}：{status_text}（{item.get('command')}）")
        checks_summary = "\n".join(f"  - {line}" for line in check_lines) if check_lines else "  - 未运行"
        any_failed = any(not item.get("passed") for item in test_results)

        report = (
            "修复流程已完成（Phase 3/4：Coder + Tester + 重试）。\n"
            f"- 问题摘要：{plan.get('problem_summary', '无')}\n"
            f"- 修改文件数：{edit_count}\n"
            f"- 重试次数：{state.get('retry_count', 0)}\n"
            f"- 检查结果：\n{checks_summary}\n"
            f"- diff 长度：{len(state.get('current_diff') or '')} 字符"
        )
        if state.get("test_note"):
            report += f"\n- 测试补充说明：{state['test_note']}"
        failure_analysis = state.get("failure_analysis") or {}
        if failure_analysis and any_failed:
            report += (
                f"\n- 失败诊断：{failure_analysis.get('failure_summary', '')}"
                f"\n- 诊断结论：{failure_analysis.get('likely_cause', '')}"
            )
        if any_failed:
            report += f"\n- 失败详情：{state.get('error_message') or '检查未通过'}"
            final_status = "tests_failed"
            status = "failed"
        elif error_message and not edit_count:
            report = f"Coder 执行失败：{error_message}"
            final_status = "failed"
            status = "failed"
        else:
            final_status = "success"
            status = "success"

        review_result = state.get("review_result") or {}
        if review_result:
            report += (
                f"\n- 审查风险：{review_result.get('risk_level', 'unknown')}"
                f"\n- 审查摘要：{review_result.get('summary', '')}"
            )
            if review_result.get("approval_required"):
                report += "\n- ⚠️ 高风险修改，建议人工复核后再合并"
                if status == "success":
                    final_status = "review_required"
                    status = "waiting_approval"

        if state.get("pr_draft"):
            report += f"\n\n---\n## PR 草稿\n\n{state['pr_draft'][:2000]}"
            if len(state.get("pr_draft") or "") > 2000:
                report += "\n\n...（PR 草稿已截断，完整内容见 pr_draft 字段）"
    elif error_message:
        report = f"任务执行失败：{error_message}"
        final_status = "failed"
        status = "failed"
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
