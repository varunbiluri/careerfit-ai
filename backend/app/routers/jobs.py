from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db import get_async_session
from app.models import Job, JobSkill, Skill
from app.schemas.job import JobListOut, JobOut
from app.services.live_job_registry import get_job as get_live_job, list_jobs as list_live_jobs
from app.services.match_service import MatchService
from app.services.resume_service import resume_exists

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = get_logger(__name__)

# Must align with GET /jobs `limit` (le=100) so the dashboard “View more jobs” control can
# actually return additional rows; a low cap here made every request return at most 5 jobs.
_MAX_JOB_LIST = 100
_SCORE_CANDIDATE_CAP = 80


def _clean_job_title(title: str | None) -> str | None:
    """Remove LinkedIn boilerplate from job title for display."""
    if not title or not title.strip():
        return title
    t = title.strip()
    for sep in ("— You may also apply directly on company website .(linkedin)", "— You may also apply directly on company website (linkedin)", ".(linkedin)", "(linkedin)"):
        if sep in t:
            t = t.split(sep)[0].strip()
    if t.endswith("—") or t.endswith(" -"):
        t = t[:-1].strip()
    return t if t else title.strip()

def _job_rows_to_out(jobs: list[Job]) -> list[JobListOut]:
    return [
        JobListOut(
            id=j.id,
            external_id=j.external_id,
            title=_clean_job_title(j.title) or j.title,
            company=j.company,
            seniority_level=j.seniority_level,
            function=j.function,
            source=j.source,
            url=j.url,
            posted_at=j.listing_posted_at or j.fetched_at or j.created_at,
        )
        for j in jobs
    ]


def _live_row_to_list_out(row: dict) -> JobListOut:
    posted = row.get("listing_posted_at") or row.get("fetched_at") or datetime.now(timezone.utc)
    return JobListOut(
        id=row["id"],
        external_id=row["external_id"],
        title=_clean_job_title(row.get("title")) or row.get("title"),
        company=row.get("company"),
        seniority_level=row.get("seniority_level"),
        function=row.get("function"),
        source=row.get("source") or "scraped",
        url=row.get("url"),
        posted_at=posted,
    )


@router.get("/", response_model=list[JobListOut])
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    resume_id: int | None = Query(
        None,
        description="When set, rank jobs by match score (desc) using existing match logic",
    ),
    seniority_level: str | None = Query(None, description="Filter by seniority (e.g. 'Senior', 'Manager', 'Director')"),
    function: str | None = Query(None, description="Filter by function (e.g. 'Engineering', 'Marketing')"),
    session: AsyncSession = Depends(get_async_session),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cap = min(limit, _MAX_JOB_LIST)

    # Freshness = last scrape (fetched_at) or row insert; excludes stale rows and static corpus.
    fresh_ts = func.coalesce(Job.fetched_at, Job.created_at)
    stmt = select(Job).where(
        Job.source.notin_(["corpus", "synthetic_fallback"]),
        fresh_ts >= cutoff,
    )
    if seniority_level:
        stmt = stmt.where(Job.seniority_level == seniority_level)
    if function:
        stmt = stmt.where(Job.function == function)

    rid = resume_id
    if rid is not None and not await resume_exists(session, rid):
        rid = None

    if rid is not None:
        stmt = stmt.order_by(fresh_ts.desc()).limit(_SCORE_CANDIDATE_CAP)
        candidates_db = list((await session.execute(stmt)).scalars().all())
        live_rows = list_live_jobs(_SCORE_CANDIDATE_CAP)
        candidates: list[SimpleNamespace] = [SimpleNamespace(id=j.id) for j in candidates_db] + [
            SimpleNamespace(id=r["id"]) for r in live_rows
        ]
        if len(candidates) < _MAX_JOB_LIST:
            logger.info(
                "job_matches: only %d jobs available after 24h filter (DB + live)",
                len(candidates),
            )
        match_svc = MatchService(session)
        scored: list[tuple[int, float]] = []
        for c in candidates:
            try:
                m = await match_svc.compute_match(c.id, rid, include_demand=True)
                ts = float((m.get("resume_score") or {}).get("total_score") or 0.0)
                scored.append((c.id, ts))
            except Exception:
                continue
        scored.sort(key=lambda x: x[1], reverse=True)
        db_by_id = {j.id: j for j in candidates_db}
        live_by_id = {r["id"]: r for r in live_rows}
        out: list[JobListOut] = []
        for jid, _ts in scored[:cap]:
            if jid in db_by_id:
                out.append(_job_rows_to_out([db_by_id[jid]])[0])
            elif jid in live_by_id:
                out.append(_live_row_to_list_out(live_by_id[jid]))
        return out

    stmt = stmt.order_by(fresh_ts.desc()).offset(skip).limit(cap)
    jobs_db = list((await session.execute(stmt)).scalars().all())
    live_rows = list_live_jobs(cap + skip + 32)
    merged: list[JobListOut] = _job_rows_to_out(jobs_db) + [_live_row_to_list_out(r) for r in live_rows]
    merged.sort(key=lambda x: x.posted_at, reverse=True)
    jobs = merged[skip : skip + cap]
    if len(jobs) < cap:
        logger.info(
            "job_matches: only %d jobs available after 24h filter (DB + live)",
            len(jobs),
        )
    return jobs

@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, session: AsyncSession = Depends(get_async_session)):
    job = await session.get(Job, job_id)
    if job:
        stmt = select(Skill.name).join(JobSkill, JobSkill.skill_id == Skill.id).where(JobSkill.job_id == job.id)
        skill_names = list((await session.execute(stmt)).scalars().all())
        return JobOut(
            id=job.id,
            external_id=job.external_id,
            title=_clean_job_title(job.title) or job.title,
            company=job.company,
            seniority_level=job.seniority_level,
            function=job.function,
            description=job.description,
            url=job.url,
            source=job.source,
            skill_names=skill_names,
        )
    row = get_live_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(
        id=row["id"],
        external_id=row["external_id"],
        title=_clean_job_title(row.get("title")) or row.get("title"),
        company=row.get("company"),
        seniority_level=row.get("seniority_level"),
        function=row.get("function"),
        description=row.get("description"),
        url=row.get("url"),
        source=row.get("source") or "scraped",
        skill_names=list(row.get("skill_names") or []),
    )
