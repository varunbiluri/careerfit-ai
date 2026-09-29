"""Aggregated role→role transitions learned from user feedback (global intelligence)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CareerTransitionStat(Base):
    __tablename__ = "career_transition_stats"
    __table_args__ = (UniqueConstraint("from_role", "to_role", name="uq_transition_roles"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    to_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
