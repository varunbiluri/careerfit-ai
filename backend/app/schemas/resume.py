from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
class ResumeCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=500)
    candidate_name: str | None = None
class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    candidate_name: str | None
    created_at: datetime
    skill_names: list[str] = []
    ai_summary: str | None = None
class ResumeAnalysisOut(BaseModel):
    resume: ResumeOut
    extracted_skills: list[str]
    raw_text_length: int


class SuggestedRolesOut(BaseModel):
    roles: list[str] = Field(default_factory=list, description="Suggested target job titles from resume heuristics")
