"""initial schema

Revision ID: 20260614_0001
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

from app.db.base import Base

import app.models.agent_step  # noqa: F401
import app.models.approval  # noqa: F401
import app.models.edit_history  # noqa: F401
import app.models.fix_task  # noqa: F401
import app.models.retrieved_context  # noqa: F401
import app.models.task_evaluation  # noqa: F401
import app.models.task_github_pr  # noqa: F401
import app.models.test_run  # noqa: F401
import app.models.tool_call  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_settings  # noqa: F401
import app.models.workflow_checkpoint  # noqa: F401

revision = "20260614_0001"
down_revision = None
branch_labels = None
depends_on = None

INITIAL_TABLE_NAMES = {
    "agent_steps",
    "approvals",
    "edit_history",
    "fix_tasks",
    "retrieved_contexts",
    "task_evaluations",
    "task_github_prs",
    "test_runs",
    "tool_calls",
    "users",
    "user_settings",
    "workflow_checkpoints",
}


def upgrade() -> None:
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in INITIAL_TABLE_NAMES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in INITIAL_TABLE_NAMES:
            table.drop(bind=bind, checkfirst=True)
