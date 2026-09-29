"""Fetch real job listings from Adzuna API (optional). Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env."""

import hashlib
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, JobSkill
from app.services.skill_service import extract_skills_from_text, get_or_create_skills

logger = get_logger(__name__)


def _external_id(adzuna_id: str) -> str:
    return "adzuna_" + hashlib.sha256(adzuna_id.encode()).hexdigest()[:24]


async def fetch_and_store_adzuna_jobs(
    session: AsyncSession,
    skill_terms: list[str],
    *,
    results_per_page: int = 20,
) -> dict:
    """
    Fetch jobs from Adzuna API by keyword and store them. Returns {"new": int, "cached": int, "error": str | None}.
    No-op if ADZUNA_APP_ID or ADZUNA_APP_KEY is not set.
    """
    settings = get_settings()
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return {"new": 0, "cached": 0, "error": None}
    what = " ".join(skill_terms[:4]) if skill_terms else "developer"
    country = (settings.adzuna_country or "us").lower()
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        f"?app_id={settings.adzuna_app_id}&app_key={settings.adzuna_app_key}"
        f"&results_per_page={results_per_page}&what={what}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Adzuna API request failed: %s", e)
        return {"new": 0, "cached": 0, "error": str(e)}
    results = data.get("results") or []
    new_count = 0
    cached_count = 0
    for item in results:
        adzuna_id = str(item.get("id", ""))
        if not adzuna_id:
            continue
        external_id = _external_id(adzuna_id)
        existing = (await session.execute(select(Job).where(Job.external_id == external_id))).scalars().one_or_none()
        if existing:
            cached_count += 1
            continue
        title = (item.get("title") or "").strip() or "Unknown"
        company = None
        if isinstance(item.get("company"), dict):
            company = (item.get("company") or {}).get("display_name") or None
        elif isinstance(item.get("company"), str):
            company = item.get("company")
        description = (item.get("description") or "")[:15000]
        redirect_url = (item.get("redirect_url") or "").strip() or None
        job = Job(
            external_id=external_id,
            title=title,
            company=company,
            seniority_level=None,
            function=None,
            description=description,
            url=redirect_url,
            source="adzuna",
        )
        session.add(job)
        await session.flush()
        skill_names = extract_skills_from_text(description)
        if skill_names:
            skills = await get_or_create_skills(session, skill_names)
            for skill in skills:
                session.add(JobSkill(job_id=job.id, skill_id=skill.id))
            await session.flush()
        new_count += 1
    return {"new": new_count, "cached": cached_count, "error": None}
