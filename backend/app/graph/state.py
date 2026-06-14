# backend/app/graph/state.py
# 作用：定义 LangGraph 的全局 State（对齐需求文档 8.1 节）
#
# State 是什么？
# LangGraph 会在每个 Node 之间传递同一个「状态字典」；
# 每个 Node 只读取自己需要的字段，并返回要更新的字段（局部 patch）。
#
# 为什么用 TypedDict 而不是 Pydantic？
# - LangGraph 官方推荐 TypedDict 描述 State，和框架集成最顺
# - Node 函数返回普通 dict 即可，不需要 model_dump()
# - API 层仍用 Pydantic（schemas/），两层职责分开
#
# total=False 是什么意思？
# - 表示字段在类型上都是「可选的」
# - 因为 State 是逐步填充的：刚启动时只有 task_id/repo_url，
#   跑到 planning_node 后才有 plan，不会一开始就有全部字段

from typing import Any, Dict, List, Optional, TypedDict


class FixPilotState(TypedDict, total=False):
    """
    FixPilot LangGraph 工作流状态（对齐需求文档 8.1）。

    数据流概览：
        用户输入 → Repository Analyst → Issue Analyst → Code Retriever
        → Planner → 人工审批 → Coder → Tester → Reviewer → PR Writer

    每个阶段往 State 里「追加/更新」自己负责的字段。
    workflow_runner 在流程结束后，把关键字段同步回 fix_tasks 表。
    """

    # ── 任务标识 ──────────────────────────────────────────────
    # 谁写入：intake_node / workflow_runner 初始化
    task_id: str          # 对应 fix_tasks.id，全流程主键
    user_id: str          # 发起任务的用户（V2 暂无登录，暂用 anonymous）

    # ── 用户原始输入（来自 fix_tasks 表）──────────────────────
    # 谁写入：workflow_runner._build_initial_state()
    repo_url: str         # GitHub 仓库地址，clone_repo_node 使用
    repo_path: Optional[str]  # clone 后的本地路径，clone_repo_node 写入
    base_branch: str      # 要基于哪个分支修改，默认 main

    issue_text: str       # Issue 原文，Issue/Retriever/Planner 都会读
    issue_url: Optional[str]  # 可选的 GitHub Issue 链接

    # ── 运行进度（前端时间线、任务列表展示用）────────────────
    # 谁写入：每个 Node 都会更新 current_* 和 status
    current_agent: str    # 当前执行的 Agent 名，如 issue_analyst、planner
    current_node: str     # 当前 LangGraph 节点名，如 classify_issue_node
    status: str           # 任务状态字符串，与 TaskStatus 枚举值对应
                          # 例：running / waiting_approval / failed

    # ── Repository Analyst 产出 ─────────────────────────────
    # 谁写入：analyze_repo_node
    project_info: Optional[Dict[str, Any]]
    # 仓库分析结果：语言、框架、测试命令、lint 命令等
    # 结构同 repo_analysis_tool.ProjectInfo.model_dump()

    file_tree_summary: Optional[str]
    # 文件树文本摘要，帮助 Planner 了解仓库结构（不塞完整目录）

    # ── Issue Analyst 产出 ───────────────────────────────────
    # 谁写入：classify_issue_node
    issue_analysis: Optional[Dict[str, Any]]
    # 结构化 issue 分析：类型、摘要、验收条件、风险等级等
    # 结构同 IssueAnalysisResult.model_dump()

    # ── Code Retriever 产出 ───────────────────────────────────
    # 谁写入：retrieve_context_node；runner 会同步到 retrieved_contexts 表
    retrieved_context: List[Dict[str, Any]]
    # 检索到的代码片段列表，每项含 file_path / line_start / snippet / score

    retrieval_quality: Dict[str, Any]
    # 检索质量摘要：是否有足够证据支撑 Planner 生成计划

    # ── Planner + 人工审批 ─────────────────────────────────────
    # 谁写入：planning_node 写 plan；approve/reject API 写 approval_*
    plan: Optional[Dict[str, Any]]
    # 修改计划：涉及文件、改动点、测试计划、风险分析
    # 结构同 FixPlan.model_dump()

    approval_status: str
    # 审批状态：pending（等待）/ approved（批准）/ rejected（拒绝）/ cancelled（取消）
    # approve_plan() / reject_plan() 在用户操作后写入

    pending_approval_type: Optional[str]
    # plan = 等待计划审批；diff_review = 等待高风险 diff 复核

    user_feedback: Optional[str]
    # 用户拒绝计划时的原因；planning_node 重新规划时会读这个字段

    allowed_files: List[str]
    # 审批通过后允许 Coder 修改的文件白名单（从 plan 提取）
    # Phase 3 Coder 只能改这里列出的路径，防止改飞

    # ── Coder 产出（Phase 3）────────────────────────────
    edit_history: List[Dict[str, Any]]  # 每次编辑的记录，写入 edit_history 表
    current_diff: Optional[str]          # 当前 git diff 文本，Reviewer 会读
    test_note: Optional[str]             # Coder 未补测试时的原因说明（FR-503）

    # ── Tester 产出（Phase 3）────────────────────────────
    # 谁写入：analyze_repo_node 可自动检测；用户创建任务时也可手动指定
    test_command: Optional[str]       # 测试命令，如 pytest
    lint_command: Optional[str]       # lint 命令，如 ruff check .
    typecheck_command: Optional[str]  # 类型检查命令，如 mypy .
    test_results: List[Dict[str, Any]]  # Docker 测试每次运行的结构化结果

    # ── Failure Diagnosis + 重试（Phase 4）──────────────
    failure_analysis: Optional[Dict[str, Any]]  # 测试失败原因分析
    retry_decision: Optional[str]  # retry | stop，retry_decision_node 写入
    retry_count: int      # 当前已重试次数，retry_decision_node 维护
    max_retries: int      # 最大重试上限，默认 2，来自 fix_tasks 表

    # ── Reviewer + PR Writer 产出（Phase 4）─────────────
    review_result: Optional[Dict[str, Any]]  # 代码审查结论、风险分级
    review_decision: Optional[str]  # proceed | high_risk
    pr_draft: Optional[str]                  # PR 标题 + 描述 Markdown 草稿

    # ── 最终结果 ─────────────────────────────────────────────
    # 谁写入：final_report_node；同步到 fix_tasks.final_report
    final_status: str
    # 工作流内部结论：running / plan_approved / waiting_approval / failed 等

    final_report: Optional[str]  # 给用户看的阶段性或最终报告（Markdown 文本）
    error_message: Optional[str]  # 任意 Node 失败时的错误摘要
