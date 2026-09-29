"""user_feedback — resume/job interaction log for behavior-weighted matching

Revision ID: 003
Revises: 002
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_feedback" in inspector.get_table_names():
        return
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_feedback_resume_id", "user_feedback", ["resume_id"])
    op.create_index("ix_user_feedback_job_id", "user_feedback", ["job_id"])
    op.create_index("ix_user_feedback_created_at", "user_feedback", ["created_at"])
    op.create_index(
        "ix_user_feedback_resume_created",
        "user_feedback",
        ["resume_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_feedback" not in inspector.get_table_names():
        return
    op.drop_index("ix_user_feedback_resume_created", table_name="user_feedback")
    op.drop_index("ix_user_feedback_created_at", table_name="user_feedback")
    op.drop_index("ix_user_feedback_job_id", table_name="user_feedback")
    op.drop_index("ix_user_feedback_resume_id", table_name="user_feedback")
    op.drop_table("user_feedback")
