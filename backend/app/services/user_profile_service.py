"""Rebuild persisted user profile from feedback across all resumes owned by the user."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobSkill, Resume, Skill, UserFeedback, UserProfile
from app.services.normalization import normalize_role

_FEEDBACK_CAP = 200
_TOP_ROLES = 18
_TOP_SKILLS = 36


def _norm_skill(s: str) -> str:
    return (s or "").strip().lower()


async def get_or_create_profile(session: AsyncSession, user_id: int) -> UserProfile:
    row = (
        await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    ).scalar_one_or_none()
    if row:
        return row
    row = UserProfile(
        user_id=user_id,
        preferred_roles=[],
        preferred_skills=[],
        interaction_history_summary=None,
    )
    session.add(row)
    await session.flush()
    return row


async def rebuild_user_profile_from_feedback(session: AsyncSession, user_id: int) -> None:
    """Aggregate clicked/applied jobs → preferred roles & skills (applied weighted higher)."""
    resume_ids = (
        await session.execute(select(Resume.id).where(Resume.user_id == user_id))
    ).scalars().all()
    if not resume_ids:
        return

    stmt = (
        select(UserFeedback.id, UserFeedback.action, UserFeedback.job_id, UserFeedback.resume_id)
        .where(UserFeedback.resume_id.in_(resume_ids))
        .where(UserFeedback.action.in_(("clicked", "applied")))
        .order_by(UserFeedback.id.desc())
        .limit(_FEEDBACK_CAP)
    )
    feed_rows = (await session.execute(stmt)).all()
    if not feed_rows:
        prof = await get_or_create_profile(session, user_id)
        prof.preferred_roles = []
        prof.preferred_skills = []
        prof.interaction_history_summary = "No clicks or applies recorded yet."
        return

    job_ids = list({r.job_id for r in feed_rows})

    jrows = (
        await session.execute(select(Job.id, Job.title).where(Job.id.in_(job_ids)))
    ).all()
    id_to_title = {jid: tit for jid, tit in jrows}

    role_w: dict[str, float] = defaultdict(float)
    skill_w: dict[str, float] = defaultdict(float)
    n_clicked = 0
    n_applied = 0

    for fr in feed_rows:
        w = 3.0 if fr.action == "applied" else 1.0
        if fr.action == "applied":
            n_applied += 1
        else:
            n_clicked += 1
        title = id_to_title.get(fr.job_id) or ""
        r = normalize_role(title)
        if r:
            role_w[r] += w

    stmt_sk = (
        select(JobSkill.job_id, Skill.name)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(JobSkill.job_id.in_(job_ids))
    )
    job_to_skills: dict[int, list[str]] = defaultdict(list)
    for jid, name in (await session.execute(stmt_sk)).all():
        if name:
            job_to_skills[jid].append(name)

    for fr in feed_rows:
        w = 3.0 if fr.action == "applied" else 1.0
        for name in job_to_skills.get(fr.job_id, []):
            sk = _norm_skill(name)
            if sk:
                skill_w[sk] += w

    top_roles = sorted(role_w.keys(), key=lambda x: -role_w[x])[:_TOP_ROLES]
    top_skills = sorted(skill_w.keys(), key=lambda x: -skill_w[x])[:_TOP_SKILLS]

    summary = (
        f"{n_clicked + n_applied} engagements (clicked/applied); "
        f"{n_applied} apply signals; top interest: {top_roles[0] if top_roles else 'n/a'}"
    )

    prof = await get_or_create_profile(session, user_id)
    prof.preferred_roles = top_roles
    prof.preferred_skills = top_skills
    prof.interaction_history_summary = summary[:2000]
