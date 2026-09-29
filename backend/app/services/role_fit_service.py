"""
Top role recommendations: resume text vs representative job blurbs (BGE cosine).
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, Resume
from app.services.embedding_service import get_embeddings_async
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id

logger = get_logger(__name__)

_MAX_ROLES = 24
_TOP_K = 3


def _fit_reason_line(title: str, fit: float) -> str:
    """Deterministic UX copy — embedding similarity vs job blurbs for this title."""
    if fit >= 78:
        return (
            f"Strong semantic overlap between your resume and recent postings titled “{title}” "
            "in our job corpus."
        )
    if fit >= 62:
        return (
            f"Several themes in your background align with “{title}” roles "
            "when compared to stored job descriptions."
        )
    return (
        f"Moderate alignment with “{title}”; adding keywords and projects typical for this title "
        "could improve fit."
    )


async def suggest_roles_from_corpus(session: AsyncSession, resume_id: int) -> list[dict]:
    """
    Return up to TOP_K roles: {"role": title, "fit": 0-100}.
    """
    resume = await session.get(Resume, resume_id)
    if resume is None and is_ephemeral_resume_id(resume_id):
        row = get_live_resume_row(resume_id)
        if row:
            resume = SimpleNamespace(raw_text=row.get("raw_text"))
    if not resume or not (resume.raw_text or "").strip():
        return []

    stmt = (
        select(Job.title, Job.description)
        .where(Job.title.isnot(None))
        .where(Job.source != "synthetic_fallback")
        .order_by(Job.id.desc())
        .limit(400)
    )
    rows = (await session.execute(stmt)).all()
    if not rows and get_settings().live_market_only:
        from app.services.live_job_registry import list_jobs as list_live_jobs

        rows = [
            (r.get("title"), r.get("description"))
            for r in list_live_jobs(400)
            if r.get("title")
        ]
    if not rows:
        return []

    # One sample row per distinct title (first seen)
    seen: set[str] = set()
    samples: list[tuple[str, str]] = []
    for title, desc in rows:
        t = (title or "").strip()
        if len(t) < 3 or t.lower() in seen:
            continue
        seen.add(t.lower())
        d = (desc or "")[:400]
        samples.append((t, f"{t}. {d}"))
        if len(samples) >= _MAX_ROLES:
            break

    if not samples:
        return []

    resume_chunk = " ".join((resume.raw_text or "").split()[:500])
    texts = [resume_chunk] + [s[1] for s in samples]
    try:
        embs = await get_embeddings_async(texts)
    except Exception as exc:
        logger.warning("suggest_roles embedding failed: %s", exc)
        return []

    if len(embs) != len(texts):
        logger.warning(
            "suggest_roles embedding count mismatch resume_id=%s expected=%s got=%s",
            resume_id,
            len(texts),
            len(embs),
        )
        return []

    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity

    r = np.array(embs[0]).reshape(1, -1)
    scores: list[tuple[str, float]] = []
    for i, (title, _) in enumerate(samples):
        v = np.array(embs[i + 1]).reshape(1, -1)
        sim = float(np.clip(cosine_similarity(r, v)[0, 0], 0.0, 1.0))
        scores.append((title, round(sim * 100.0, 1)))

    scores.sort(key=lambda x: -x[1])
    out = [{"role": t, "fit": f, "fit_reason": _fit_reason_line(t, f)} for t, f in scores[:_TOP_K]]
    return out
