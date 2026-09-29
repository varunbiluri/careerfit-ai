"""
Persistent job corpus (backend/data/job_corpus.json) — survives scraper failure.

Seeded at startup when DB job count is below threshold, and on-demand during
gap analysis if the market would otherwise be empty.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, JobSkill, Skill

logger = get_logger(__name__)

_CORPUS_VERSION = "v1"


def job_corpus_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "job_corpus.json"


def load_corpus_raw() -> list[dict[str, Any]]:
    path = job_corpus_path()
    if not path.exists():
        logger.warning("job_corpus.json missing at %s — run scripts/bootstrap_job_corpus.py", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


async def count_jobs(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(Job.id)))).scalar() or 0)


async def count_corpus_jobs(session: AsyncSession) -> int:
    stmt = select(func.count(Job.id)).where(Job.source == "corpus")
    return int((await session.execute(stmt)).scalar() or 0)


async def infer_demand_source(session: AsyncSession) -> str:
    """
    real — substantial scraped/third-party jobs in DB
    corpus — curated JSON corpus dominates
    synthetic — only tiny synthetic_fallback rows
    """
    total = await count_jobs(session)
    if total == 0:
        return "synthetic"
    stmt_real = select(func.count(Job.id)).where(
        Job.source.notin_(["corpus", "synthetic_fallback"])
    )
    n_real = int((await session.execute(stmt_real)).scalar() or 0)
    if n_real >= 8:
        return "real"
    stmt_corpus = select(func.count(Job.id)).where(Job.source == "corpus")
    n_corpus = int((await session.execute(stmt_corpus)).scalar() or 0)
    if n_corpus >= 20:
        return "corpus"
    if n_real > 0:
        return "real"
    if n_corpus > 0:
        return "corpus"
    return "synthetic"


async def seed_corpus_if_needed(session: AsyncSession, threshold: int | None = None) -> int:
    """
    Insert jobs from job_corpus.json until DB has at least `threshold` jobs
    (or all corpus rows are inserted). Idempotent via external_id.

    Returns number of new Job rows inserted.
    """
    settings = get_settings()
    th = threshold if threshold is not None else getattr(settings, "job_corpus_seed_threshold", 100)
    current = await count_jobs(session)
    if current >= th:
        return 0

    entries = load_corpus_raw()
    if not entries:
        logger.warning("seed_corpus_if_needed: no corpus entries to load")
        return 0

    from app.services.skill_service import get_or_create_skills

    inserted = 0
    now = datetime.now(timezone.utc)
    need = th - current

    for i, row in enumerate(entries):
        if inserted >= need and current + inserted >= th:
            break
        title = (row.get("title") or "Software Engineer").strip()
        desc = (row.get("description") or "").strip()
        raw_skills = row.get("skills") or []
        skills_lower: list[str] = []
        if isinstance(raw_skills, list):
            for s in raw_skills:
                if isinstance(s, str) and s.strip():
                    skills_lower.append(s.strip().lower())
        ex_id = f"corpus:{_CORPUS_VERSION}:{i:05d}"
        exists = (await session.execute(select(Job.id).where(Job.external_id == ex_id))).scalar_one_or_none()
        if exists is not None:
            continue
        job = Job(
            external_id=ex_id,
            title=title[:500],
            company="Curated market corpus",
            description=desc[:15000] if desc else f"{title} role. Skills: {', '.join(skills_lower[:12])}.",
            url=None,
            source="corpus",
            fetched_at=now,
        )
        session.add(job)
        await session.flush()
        if skills_lower:
            skills = await get_or_create_skills(session, skills_lower)
            for sk in skills:
                session.add(JobSkill(job_id=job.id, skill_id=sk.id))
        inserted += 1

    if inserted:
        logger.info(
            "job_corpus: inserted %d job(s) from job_corpus.json (threshold=%d)",
            inserted,
            th,
        )
    return inserted


async def ensure_minimum_market_jobs(session: AsyncSession, min_jobs: int = 50) -> tuple[int, str]:
    """
    If DB has fewer than min_jobs, try to seed from corpus. Returns
    (inserted_count, action) where action is 'seeded'|'skipped'|'no_corpus'.
    """
    n = await count_jobs(session)
    if n >= min_jobs:
        return 0, "skipped"
    added = await seed_corpus_if_needed(session, threshold=max(min_jobs, n + 1))
    if added:
        return added, "seeded"
    if n == 0 and load_corpus_raw():
        return 0, "no_corpus"
    return 0, "skipped"
