# backend/app/core/tool_permissions.py
# Purpose: central policy for tool permission levels.
#
# Keeping this in one place makes permission decisions testable. It also avoids
# scattering "is this high risk?" checks across agents, workflow code and APIs.

from app.models.tool_call import PermissionLevel


TOOL_PERMISSION_LEVELS: dict[str, PermissionLevel] = {
    # Read-only tools.
    "read_file_tool": PermissionLevel.LOW,
    "semantic_search_tool": PermissionLevel.LOW,
    "keyword_search_tool": PermissionLevel.LOW,
    "hybrid_search_tool": PermissionLevel.LOW,
    "git_diff_tool": PermissionLevel.LOW,
    # Limited side-effect tools.
    "repo_clone_tool": PermissionLevel.MEDIUM,
    "repo_analysis_tool": PermissionLevel.LOW,
    # High-risk tools. These must be protected by approval, sandboxing, or both.
    "edit_file_tool": PermissionLevel.HIGH,
    "run_tests_tool": PermissionLevel.HIGH,
    "run_lint_tool": PermissionLevel.HIGH,
    "run_typecheck_tool": PermissionLevel.HIGH,
    "create_branch_tool": PermissionLevel.HIGH,
    "commit_tool": PermissionLevel.HIGH,
    "create_pr_tool": PermissionLevel.HIGH,
    "dependency_install_tool": PermissionLevel.HIGH,
    "rollback_retry_tool": PermissionLevel.HIGH,
}


def get_tool_permission(tool_name: str) -> PermissionLevel:
    """
    Return a tool's permission level.

    Unknown tools default to HIGH. That is safer for beginners because a new
    tool must be explicitly reviewed before it is treated as low risk.
    """

    return TOOL_PERMISSION_LEVELS.get(tool_name, PermissionLevel.HIGH)


def tool_requires_guard(tool_name: str) -> bool:
    """
    Whether the tool needs approval, sandboxing, or another protective guard.
    """

    return get_tool_permission(tool_name) == PermissionLevel.HIGH
