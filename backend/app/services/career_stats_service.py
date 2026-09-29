"""
Learning loop: job feedback persistence, behavior-weighted match boost, skill popularity counters.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.core.logging import get_logger
from app.models import JobSkill, Skill, UserFeedback
from app.services.live_resume_registry import is_ephemeral_resume_id
from app.services.normalization import normalize_role

logger = get_logger(__name__)

ActionLiteral = Literal["viewed", "clicked", "applied"]

# In-process fallback when Redis is disabled (dev / tests).
_local_miss: dict[str, int] = defaultdict(int)
_local_sim: dict[str, int] = defaultdict(int)

_FEEDBACK_LOOKBACK = 80
_MAX_BEHAVIOR_BOOST_POINTS = 10.0  # maps spec "behavior_score" to meaningful 0–100 scale
_MAX_ROLE_PROFILE_BOOST = 8.0


async def _redis_incr(key: str) -> int | None:
    r = get_redis()
    if r is None:
        return None
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 86400 * 90)
        return int(n)
    except Exception as exc:
        logger.debug("redis incr %s: %s", key, exc)
        return None


def _norm_skill(s: str) -> str:
    return (s or "").strip().lower()


async def record_missing_skill_stats(skill_names: list[str]) -> None:
    for raw in skill_names[:40]:
        k = _norm_skill(raw)
        if not k:
            continue
        key = f"career:stat:miss:{k}"
        n = await _redis_incr(key)
        if n is None:
            _local_miss[k] += 1


async def record_simulated_skill_stats(skill_names: list[str]) -> None:
    for raw in skill_names[:40]:
        k = _norm_skill(raw)
        if not k:
            continue
        key = f"career:stat:sim:{k}"
        n = await _redis_incr(key)
        if n is None:
            _local_sim[k] += 1


async def add_user_job_feedback(
    session: AsyncSession,
    *,
    resume_id: int,
    job_id: int,
    action: str,
) -> None:
    if action not in ("viewed", "clicked", "applied"):
        raise ValueError("action must be viewed, clicked, or applied")
    if is_ephemeral_resume_id(resume_id):
        logger.debug("skip UserFeedback row for ephemeral resume_id=%s", resume_id)
        return
    session.add(UserFeedback(resume_id=resume_id, job_id=job_id, action=action))
    await session.flush()


async def preference_skills_for_match(
    session: AsyncSession,
    resume_id: int,
    profile_skill_names: list[str] | None,
) -> set[str]:
    """Recent click/apply job skills plus persisted profile.preferred_skills."""
    base = await preference_skill_names(session, resume_id)
    if profile_skill_names:
        base |= {_norm_skill(s) for s in profile_skill_names if s}
    return base


async def preference_skill_names(
    session: AsyncSession,
    resume_id: int,
    *,
    limit_jobs: int = 25,
) -> set[str]:
    """
    Union of job skill names from jobs this resume recently clicked or applied to.
    """
    stmt = (
        select(UserFeedback.job_id)
        .where(UserFeedback.resume_id == resume_id)
        .where(UserFeedback.action.in_(("clicked", "applied")))
        .order_by(UserFeedback.id.desc())
        .limit(_FEEDBACK_LOOKBACK)
    )
    job_ids = list(dict.fromkeys((await session.execute(stmt)).scalars().all()))
    if not job_ids:
        return set()
    job_ids = job_ids[:limit_jobs]
    stmt2 = (
        select(Skill.name)
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .where(JobSkill.job_id.in_(job_ids))
    )
    rows = (await session.execute(stmt2)).scalars().all()
    return {_norm_skill(n) for n in rows if n}


def compute_role_preference_boost_points(
    job_title: str | None,
    preferred_roles: list[str] | None,
) -> tuple[float, str]:
    """Boost when job title matches roles inferred from the user's clicks/applies."""
    if not preferred_roles:
        return 0.0, ""
    jn = normalize_role(job_title or "").strip().lower()
    if not jn:
        return 0.0, ""
    for i, pr in enumerate(preferred_roles[:14]):
        pn = normalize_role(str(pr)).strip().lower()
        if not pn:
            continue
        if pn == jn or pn in jn or jn in pn:
            pts = max(0.0, _MAX_ROLE_PROFILE_BOOST - i * 0.55)
            pts = round(min(_MAX_ROLE_PROFILE_BOOST, pts), 2)
            disp = str(pr).strip() or pn
            return pts, f"+{pts:.1f} pts: matches roles you engage with ({disp})"
    return 0.0, ""


def compute_behavior_boost_points(
    job_skill_names: list[str],
    preference_skills: set[str],
) -> tuple[float, str]:
    """
    Returns (boost_points 0..MAX_BEHAVIOR_BOOST_POINTS, short reason).
    Overlap fraction * max points; normalized "behavior_score" in API = boost/100 ∈ [0,0.1].
    """
    if not preference_skills or not job_skill_names:
        return 0.0, ""
    js = {_norm_skill(s) for s in job_skill_names if s}
    if not js:
        return 0.0, ""
    inter = js & preference_skills
    overlap = len(inter) / len(js)
    boost = round(min(_MAX_BEHAVIOR_BOOST_POINTS, overlap * _MAX_BEHAVIOR_BOOST_POINTS), 2)
    if boost <= 0:
        return 0.0, ""
    reason = (
        f"+{boost:.1f} pts: job skills overlap {len(inter)}/{len(js)} with roles you clicked or applied to"
    )
    return boost, reason
