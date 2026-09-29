from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.skill import Skill

class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    candidate_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # TODO: move raw_text to object storage (S3/GCS) and store only a URI here.
    # At 100k resumes × ~5KB avg = ~500MB in a single TEXT column; SQLAlchemy
    # loads the full column on every session.get(Resume, id) call.
    # Migration path: add a raw_text_uri column, backfill, then drop raw_text.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Nullable FK → users.id; SET NULL on user delete preserves the resume row.
    # NOTE: adding this column to an existing 'resumes' table requires an Alembic migration
    # (create_all won't ALTER existing tables). Run: alembic revision --autogenerate && alembic upgrade head
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resume_skills: Mapped[list["ResumeSkill"]] = relationship("ResumeSkill", back_populates="resume", cascade="all, delete-orphan")
    def __repr__(self) -> str:
        return f"<Resume(id={self.id}, filename={self.filename!r})>"

class ResumeSkill(Base):
    __tablename__ = "resume_skills"
    __table_args__ = (
        UniqueConstraint("resume_id", "skill_id", name="uq_resume_skill"),
        Index("ix_resume_skills_resume_id", "resume_id"),
        Index("ix_resume_skills_skill_id", "skill_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    resume: Mapped["Resume"] = relationship("Resume", back_populates="resume_skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="resume_skills")
    def __repr__(self) -> str:
        return f"<ResumeSkill(resume_id={self.resume_id}, skill_id={self.skill_id})>"
