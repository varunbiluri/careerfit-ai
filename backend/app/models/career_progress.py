"""Time-series snapshots of market fit for journey memory (authenticated users)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CareerProgress(Base):
    __tablename__ = "career_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    skills_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    roles_considered: Mapped[list | None] = mapped_column(JSON, nullable=False, default=list)

    user = relationship("User", backref="career_progress_snapshots", lazy="selectin")
    resume = relationship("Resume", backref="career_progress_snapshots", lazy="selectin")
