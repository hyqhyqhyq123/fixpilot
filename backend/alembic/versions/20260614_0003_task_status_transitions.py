"""task status transition audit

Revision ID: 20260614_0003
Revises: 20260614_0002
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0003"
down_revision = "20260614_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_status_transitions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=False),
        sa.Column("to_status", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["fix_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_status_transitions_task_id",
        "task_status_transitions",
        ["task_id"],
    )
    op.create_index(
        "ix_task_status_transitions_task_created",
        "task_status_transitions",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_task_status_transitions_from_to",
        "task_status_transitions",
        ["from_status", "to_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_status_transitions_from_to", table_name="task_status_transitions")
    op.drop_index("ix_task_status_transitions_task_created", table_name="task_status_transitions")
    op.drop_index("ix_task_status_transitions_task_id", table_name="task_status_transitions")
    op.drop_table("task_status_transitions")
