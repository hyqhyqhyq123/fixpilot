# backend/app/graph/state.py
# 作用：定义 LangGraph 的全局 State（对齐需求文档 8.1 节）
#
# State 是什么？
# LangGraph 会在每个 Node 之间传递同一个 State 字典；
# 每个 Node 读取自己需要的字段，并返回要更新的字段。

from typing import Any, Dict, List, Optional, TypedDict


class FixPilotState(TypedDict, total=False):
    """FixPilot LangGraph 工作流状态（对齐需求文档 8.1）。"""

    task_id: str
    user_id: str

    repo_url: str
    repo_path: Optional[str]
    base_branch: str

    issue_text: str
    issue_url: Optional[str]

    current_agent: str
    current_node: str
    status: str

    project_info: Optional[Dict[str, Any]]
    file_tree_summary: Optional[str]

    issue_analysis: Optional[Dict[str, Any]]
    retrieved_context: List[Dict[str, Any]]

    plan: Optional[Dict[str, Any]]
    approval_status: str
    user_feedback: Optional[str]

    allowed_files: List[str]

    edit_history: List[Dict[str, Any]]
    current_diff: Optional[str]

    test_command: Optional[str]
    lint_command: Optional[str]
    typecheck_command: Optional[str]
    test_results: List[Dict[str, Any]]

    failure_analysis: Optional[Dict[str, Any]]
    retry_count: int
    max_retries: int

    review_result: Optional[Dict[str, Any]]
    pr_draft: Optional[str]

    final_status: str
    final_report: Optional[str]
    error_message: Optional[str]
