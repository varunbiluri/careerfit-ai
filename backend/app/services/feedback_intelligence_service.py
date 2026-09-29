"""Post-feedback hooks: global aggregates, transition stats, user profile rebuild."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CareerTransitionStat, Job, Resume, UserFeedback
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id
from app.services.global_intel_service import record_job_engagement_global
from app.services.normalization import normalize_role
from app.services.user_profile_service import rebuild_user_profile_from_feedback


async def _increment_transition(
    session: AsyncSession,
    from_role: str,
    to_role: str,
    weight: int,
) -> None:
    if not from_role or not to_role or from_role == to_role:
        return
    stmt = select(CareerTransitionStat).where(
        CareerTransitionStat.from_role == from_role,
        CareerTransitionStat.to_role == to_role,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row:
        row.weight = int(row.weight) + weight
    else:
        session.add(
            CareerTransitionStat(from_role=from_role, to_role=to_role, weight=weight),
        )


async def record_learned_transition(session: AsyncSession, user_id: int, action: str) -> None:
    """
    If this user has a prior clicked/applied job, treat (previous_title → current_title)
    as a weak career-transition observation. Applies double weight on apply.
    """
    if action not in ("clicked", "applied"):
        return
    w = 3 if action == "applied" else 1
    stmt = (
        select(Job.title)
        .select_from(UserFeedback)
        .join(Resume, Resume.id == UserFeedback.resume_id)
        .join(Job, Job.id == UserFeedback.job_id)
        .where(Resume.user_id == user_id)
        .where(UserFeedback.action.in_(("clicked", "applied")))
        .order_by(UserFeedback.id.desc())
        .limit(2)
    )
    titles = list((await session.execute(stmt)).scalars().all())
    if len(titles) < 2:
        return
    prev_t, new_t = titles[1], titles[0]
    prev_r = normalize_role(prev_t or "").strip().lower()
    new_r = normalize_role(new_t or "").strip().lower()
    await _increment_transition(session, prev_r, new_r, w)


async def on_job_feedback_recorded(
    session: AsyncSession,
    *,
    resume_id: int,
    job_id: int,
    action: str,
) -> None:
    await record_job_engagement_global(session, job_id, action)
    resume = await session.get(Resume, resume_id)
    if resume is None and is_ephemeral_resume_id(resume_id):
        row = get_live_resume_row(resume_id)
        uid = row.get("user_id") if row else None
    else:
        uid = resume.user_id if resume else None
    if uid is not None:
        await record_learned_transition(session, uid, action)
        await rebuild_user_profile_from_feedback(session, uid)
