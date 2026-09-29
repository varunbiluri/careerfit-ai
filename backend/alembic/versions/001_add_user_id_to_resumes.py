"""Add user_id FK to resumes table

This migration adds the nullable user_id column to the resumes table so that
resumes can be linked to authenticated users.  The column is nullable so that
existing rows (created before authentication was introduced) remain valid.

On delete: SET NULL — deleting a user preserves their resumes without ownership.

Revision ID: 001
Revises: (initial — no previous migration)
Create Date: 2026-03-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the users table first (it may not exist on databases that were
    # bootstrapped via create_all before the User model was added).
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=60), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Silently skip if the table already exists (idempotent on fresh installs)
        if_not_exists=True,
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True, if_not_exists=True)

    # Add user_id column to resumes (nullable so existing rows are unaffected)
    # Use a conditional check so the migration is re-runnable on partial installs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = [c["name"] for c in inspector.get_columns("resumes")]
    if "user_id" not in existing_cols:
        op.add_column(
            "resumes",
            sa.Column("user_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_resumes_user_id",
            "resumes",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_resumes_user_id", "resumes", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = [c["name"] for c in inspector.get_columns("resumes")]
    if "user_id" in existing_cols:
        op.drop_index("ix_resumes_user_id", table_name="resumes")
        op.drop_constraint("fk_resumes_user_id", "resumes", type_="foreignkey")
        op.drop_column("resumes", "user_id")
    op.drop_table("users")
