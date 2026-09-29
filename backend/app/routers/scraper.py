from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_async_session
from app.models import Job, JobSkill, Skill
from app.schemas.job import JobOut
from app.services.scraper_service import ScraperService

router = APIRouter(prefix="/scraper", tags=["scraper"])


class ScrapeSearchPageBody(BaseModel):
    """Body for n8n-style import: send a search results URL (e.g. LinkedIn with f_TPR=r86400 for last 24h)."""
    url: str = Field(..., description="Full LinkedIn search URL (e.g. with f_TPR=r86400 for last 24h)")
    max_jobs: int = Field(30, ge=1, le=100, description="Max job links to scrape from the page")


@router.post("/scrape-search-page")
async def scrape_search_page(body: ScrapeSearchPageBody, session: AsyncSession = Depends(get_async_session)):
    """
    Scrape jobs from a search results page URL (e.g. built by n8n).
    Use this when you build a URL with filters like:
    - LinkedIn: f_TPR=r3600 (last 1h), r86400 (last 24h), plus keywords, location, experience, remote, job type.
    We fetch the URL, parse job detail links, and store each job.
    """
    url = body.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    service = ScraperService(session)
    result = await service.scrape_search_page(url, max_jobs=body.max_jobs)
    await session.commit()
    return {"ok": True, **result}


@router.post("/scrape", response_model=JobOut)
async def scrape_job_url(url: str = Query(..., description="Public job listing URL"), session: AsyncSession = Depends(get_async_session)):
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    service = ScraperService(session)
    job, _skills = await service.scrape_and_store(url)
    await session.commit()
    if not job:
        raise HTTPException(status_code=502, detail="Scrape failed or returned no content")
    stmt = select(Skill.name).join(JobSkill, JobSkill.skill_id == Skill.id).where(JobSkill.job_id == job.id)
    skill_names = list((await session.execute(stmt)).scalars().all())
    return JobOut(id=job.id, external_id=job.external_id, title=job.title, company=job.company, seniority_level=job.seniority_level, function=job.function, description=job.description, url=job.url, source=job.source, skill_names=skill_names)
