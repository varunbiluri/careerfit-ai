from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.skill import Skill

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company: Mapped[str | None] = mapped_column(String(500), nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)  # e.g. "Director", "Manager", "Senior", "Associate", "Junior"
    function: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # e.g. "Engineering", "Marketing", "Sales", "Data Science"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="csv")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True  # needed for skill_trends() date_trunc query
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # fetched_at: when the job page was last successfully scraped (distinct from
    # created_at which never changes after insert).  Used by freshness checks to
    # decide whether a re-scrape is needed.  Null for jobs imported before this
    # column existed (treated as stale).
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # When the employer/source says the job was posted (e.g. LinkedIn JSON-LD or "N hours ago").
    listing_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    job_skills: Mapped[list["JobSkill"]] = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan")
    def __repr__(self) -> str:
        return f"<Job(id={self.id}, external_id={self.external_id!r})>"

class JobSkill(Base):
    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill_id", name="uq_job_skill"),
        Index("ix_job_skills_job_id", "job_id"),
        Index("ix_job_skills_skill_id", "skill_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    job: Mapped["Job"] = relationship("Job", back_populates="job_skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="job_skills")
    def __repr__(self) -> str:
        return f"<JobSkill(job_id={self.job_id}, skill_id={self.skill_id})>"
