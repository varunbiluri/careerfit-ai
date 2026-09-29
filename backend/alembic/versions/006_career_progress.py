"""career_progress — fit snapshots over time per user/resume

Revision ID: 006
Revises: 005
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "career_progress" in inspector.get_table_names():
        return
    op.create_table(
        "career_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=False),
        sa.Column("skills_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("roles_considered", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_career_progress_user_id", "career_progress", ["user_id"])
    op.create_index("ix_career_progress_resume_id", "career_progress", ["resume_id"])
    op.create_index("ix_career_progress_snapshot_at", "career_progress", ["snapshot_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "career_progress" not in inspector.get_table_names():
        return
    op.drop_index("ix_career_progress_snapshot_at", table_name="career_progress")
    op.drop_index("ix_career_progress_resume_id", table_name="career_progress")
    op.drop_index("ix_career_progress_user_id", table_name="career_progress")
    op.drop_table("career_progress")
