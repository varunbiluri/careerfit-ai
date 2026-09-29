from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
class JobCreate(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=255)
    title: str | None = None
    company: str | None = None
    seniority_level: str | None = None  # e.g. "Director", "Manager", "Senior", "Associate", "Junior"
    function: str | None = None  # e.g. "Engineering", "Marketing", "Sales", "Data Science"
    description: str | None = None
    url: str | None = None
    source: str = "csv"
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: str
    title: str | None
    company: str | None
    seniority_level: str | None
    function: str | None
    description: str | None
    url: str | None
    source: str
    skill_names: list[str] = []
class JobListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: str
    title: str | None
    company: str | None
    seniority_level: str | None
    function: str | None
    source: str
    url: str | None = None
    # When the listing was last seen in our pipeline (scrape time) or first ingested.
    posted_at: datetime
