# backend/test/test_tool_permissions.py
# Purpose: verify the central tool permission policy.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.tool_permissions import get_tool_permission, tool_requires_guard
from app.models.tool_call import PermissionLevel
from app.services.workflow_runner import NODE_TOOL_MAP


def test_known_tools_have_expected_permission_levels():
    assert get_tool_permission("read_file_tool") == PermissionLevel.LOW
    assert get_tool_permission("semantic_search_tool") == PermissionLevel.LOW
    assert get_tool_permission("repo_clone_tool") == PermissionLevel.MEDIUM
    assert get_tool_permission("edit_file_tool") == PermissionLevel.HIGH
    assert get_tool_permission("run_tests_tool") == PermissionLevel.HIGH
    assert get_tool_permission("create_pr_tool") == PermissionLevel.HIGH
    assert get_tool_permission("rollback_retry_tool") == PermissionLevel.HIGH


def test_unknown_tools_default_to_high_risk():
    assert get_tool_permission("new_unreviewed_tool") == PermissionLevel.HIGH
    assert tool_requires_guard("new_unreviewed_tool") is True


def test_high_risk_tools_require_guard():
    assert tool_requires_guard("edit_file_tool") is True
    assert tool_requires_guard("run_tests_tool") is True
    assert tool_requires_guard("read_file_tool") is False


def test_workflow_audit_map_uses_central_policy():
    for tool_name, permission in NODE_TOOL_MAP.values():
        assert permission == get_tool_permission(tool_name)
