"""Add listing_posted_at to jobs — employer/source listing time when parsed (e.g. LinkedIn).

Revision ID: 007
Revises: 006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("jobs")]
    if "listing_posted_at" not in existing:
        op.add_column(
            "jobs",
            sa.Column("listing_posted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_jobs_listing_posted_at", "jobs", ["listing_posted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("jobs")]
    if "listing_posted_at" in existing:
        op.drop_index("ix_jobs_listing_posted_at", table_name="jobs")
        op.drop_column("jobs", "listing_posted_at")
