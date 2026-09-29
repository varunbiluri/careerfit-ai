"""Add fetched_at column to jobs table

fetched_at records when a job page was last successfully scraped.  Distinct
from created_at (set once on insert) and updated_at (set by ORM onupdate).
Used by the freshness cache to skip re-scraping within the configured window.

Revision ID: 002
Revises: 001
Create Date: 2026-03-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("jobs")]
    if "fetched_at" not in existing:
        op.add_column(
            "jobs",
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_jobs_fetched_at", "jobs", ["fetched_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("jobs")]
    if "fetched_at" in existing:
        op.drop_index("ix_jobs_fetched_at", table_name="jobs")
        op.drop_column("jobs", "fetched_at")
