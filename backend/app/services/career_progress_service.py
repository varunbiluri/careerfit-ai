"""Append-only fit snapshots and simple improvement / peer-benchmark heuristics."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import CareerProgress, Resume
from app.services.live_resume_registry import is_ephemeral_resume_id

logger = get_logger(__name__)


async def record_career_progress_snapshot(
    session: AsyncSession,
    *,
    resume: Resume,
    fit_score: float,
    skills_count: int,
    roles_considered: list[str],
) -> None:
    if resume.user_id is None or is_ephemeral_resume_id(int(getattr(resume, "id", 0))):
        return
    roles_json = list(roles_considered[:24])
    session.add(
        CareerProgress(
            user_id=resume.user_id,
            resume_id=resume.id,
            fit_score=float(fit_score),
            skills_count=int(skills_count),
            roles_considered=roles_json,
        )
    )
    await session.flush()


async def fetch_progress_series(
    session: AsyncSession,
    *,
    user_id: int,
    resume_id: int | None = None,
    limit: int = 120,
) -> list[CareerProgress]:
    stmt = select(CareerProgress).where(CareerProgress.user_id == user_id)
    if resume_id is not None:
        stmt = stmt.where(CareerProgress.resume_id == resume_id)
    stmt = stmt.order_by(CareerProgress.snapshot_at.asc()).limit(max(1, min(500, limit)))
    return list((await session.execute(stmt)).scalars().all())


def improvement_rate_per_week(points: list[CareerProgress]) -> float:
    """Δ fit / Δ weeks between first and last snapshot (0 if insufficient data)."""
    if len(points) < 2:
        return 0.0
    first, last = points[0], points[-1]
    t0 = first.snapshot_at
    t1 = last.snapshot_at
    if t0 is None or t1 is None or t1 <= t0:
        return 0.0
    weeks = (t1 - t0).total_seconds() / (86400 * 7.0)
    if weeks < 0.25:
        return 0.0
    return round((last.fit_score - first.fit_score) / weeks, 3)


def peer_improvement_percentile(improvement_per_week: float) -> int:
    """
    Deterministic percentile vs a fixed reference curve (not live A/B).
    improvement_per_week in roughly [-5, +5] fit points/week for UX.
    """
    # Map slope to 10–92 percentile band
    x = improvement_per_week
    p = 50 + 18 * math.tanh(x / 1.8)
    return int(max(10, min(92, round(p))))


async def median_switch_weeks_hint(session: AsyncSession) -> int:
    """Shorter when aggregate transitions are heavily observed (explainable aggregate)."""
    from sqlalchemy import func

    from app.models import CareerTransitionStat

    avg_w = await session.scalar(select(func.avg(CareerTransitionStat.weight)))
    if avg_w is None or float(avg_w) < 1.5:
        return 7
    aw = float(avg_w)
    return int(max(4, min(12, round(11 - min(5.0, (aw - 1.0) * 0.35)))))


def insight_lines_for_progress(
    *,
    improvement_per_week: float,
    peer_pct: int,
    n_points: int,
    median_switch_weeks: int,
) -> list[str]:
    lines: list[str] = []
    if n_points >= 3 and improvement_per_week > 0.08:
        lines.append(
            f"You are improving faster than about {peer_pct}% of users in our reference curve "
            f"(~{improvement_per_week:+.2f} fit points/week across your saved snapshots)."
        )
    elif n_points >= 3 and improvement_per_week < -0.08:
        lines.append(
            "Your saved fit trend is declining — consider refreshing skills or target role alignment."
        )
    lines.append(
        f"In aggregate data, similar role moves often show first intent within ~{median_switch_weeks} weeks "
        "(heuristic from global transition counts, not a guarantee)."
    )
    return lines
