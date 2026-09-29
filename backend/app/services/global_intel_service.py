"""Cross-user usage aggregates (Redis sorted sets + local fallback) and DB transition stats."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.core.logging import get_logger
from app.models import CareerTransitionStat, Job, JobSkill, Skill

logger = get_logger(__name__)

KEY_SKILL_CLICKS = "career:global:skill_clicks"
KEY_ROLE_INTEREST = "career:global:role_interest"

# In-process mirror when Redis is off (dev/tests).
_local_z: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))


async def zincr_global_sorted(key: str, member: str, inc: float) -> None:
    if inc <= 0 or not member:
        return
    r = get_redis()
    if r is not None:
        try:
            await r.zincrby(key, inc, member)
            await r.expire(key, 86400 * 180)
        except Exception as exc:
            logger.debug("zincr %s: %s", key, exc)
    _local_z[key][member] += inc


async def zrevrange_with_scores(key: str, top_n: int) -> list[dict]:
    r = get_redis()
    if r is not None:
        try:
            raw = await r.zrevrange(key, 0, max(0, top_n - 1), withscores=True)
            out: list[dict] = []
            for m, s in raw or []:
                name = m.decode() if isinstance(m, bytes) else str(m)
                out.append({"name": name, "score": round(float(s), 2)})
            return out
        except Exception as exc:
            logger.debug("zrevrange %s: %s", key, exc)
    bucket = _local_z.get(key, {})
    items = sorted(bucket.items(), key=lambda x: -x[1])[:top_n]
    return [{"name": k, "score": round(float(v), 2)} for k, v in items]


async def record_job_engagement_global(session: AsyncSession, job_id: int, action: str) -> None:
    """Increment global skill + role counters from one feedback event."""
    if action not in ("clicked", "applied"):
        return
    w = 3.0 if action == "applied" else 1.0
    job = await session.get(Job, job_id)
    if not job:
        return
    from app.services.normalization import normalize_role

    rn = normalize_role(job.title or "")
    if rn:
        await zincr_global_sorted(KEY_ROLE_INTEREST, rn, w)

    stmt = (
        select(Skill.name)
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .where(JobSkill.job_id == job_id)
        .limit(80)
    )
    for name in (await session.execute(stmt)).scalars().all():
        k = (name or "").strip().lower()
        if k:
            await zincr_global_sorted(KEY_SKILL_CLICKS, k, w)


async def fetch_common_transitions(session: AsyncSession, limit: int = 24) -> list[dict]:
    stmt = (
        select(CareerTransitionStat)
        .order_by(CareerTransitionStat.weight.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "from_role": r.from_role,
            "to_role": r.to_role,
            "weight": r.weight,
        }
        for r in rows
    ]


async def build_global_insights_payload(session: AsyncSession) -> dict:
    from app.services.skill_service import skill_trends_fastest_declining

    top_skills = await zrevrange_with_scores(KEY_SKILL_CLICKS, 25)
    role_interest = await zrevrange_with_scores(KEY_ROLE_INTEREST, 20)
    transitions = await fetch_common_transitions(session, 24)
    fastest, _decl, weeks = await skill_trends_fastest_declining(session, weeks=8, limit=12)
    velocity = [
        {
            "skill_name": t.get("skill_name") or "",
            "weekly_growth_pct": t.get("weekly_growth_pct"),
            "demand_percentage": t.get("demand_percentage"),
        }
        for t in fastest
        if t.get("skill_name")
    ]
    return {
        "top_skills": top_skills,
        "emerging_roles": role_interest,
        "common_transitions": transitions,
        "fastest_adopted_skills": velocity,
        "trend_weeks_available": weeks,
    }
