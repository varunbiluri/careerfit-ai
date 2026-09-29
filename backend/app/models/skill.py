from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.job import JobSkill
    from app.models.resume import ResumeSkill

class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job_skills: Mapped[list["JobSkill"]] = relationship("JobSkill", back_populates="skill", cascade="all, delete-orphan")
    resume_skills: Mapped[list["ResumeSkill"]] = relationship("ResumeSkill", back_populates="skill", cascade="all, delete-orphan")
    def __repr__(self) -> str:
        return f"<Skill(id={self.id}, name={self.name!r})>"
