"""career_transition_stats — learned global role→role edges

Revision ID: 005
Revises: 004
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "career_transition_stats" in inspector.get_table_names():
        return
    op.create_table(
        "career_transition_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_role", sa.String(length=160), nullable=False),
        sa.Column("to_role", sa.String(length=160), nullable=False),
        sa.Column("weight", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_role", "to_role", name="uq_transition_roles"),
    )
    op.create_index("ix_cts_from_role", "career_transition_stats", ["from_role"])
    op.create_index("ix_cts_to_role", "career_transition_stats", ["to_role"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "career_transition_stats" not in inspector.get_table_names():
        return
    op.drop_index("ix_cts_to_role", table_name="career_transition_stats")
    op.drop_index("ix_cts_from_role", table_name="career_transition_stats")
    op.drop_table("career_transition_stats")
