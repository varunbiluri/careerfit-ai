"""
Predictive career trajectory from weighted role graph + per-role gap shape + global transitions.
All heuristics are explicit (no learned black-box).
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CareerTransitionStat, Resume
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id
from app.services.career_path_service import weighted_next_roles
from app.services.match_service import MatchService
from app.services.normalization import normalize_role
from app.services.role_fit_service import suggest_roles_from_corpus


def _avg_top_demand(high_demand_missing: list[dict], k: int = 5) -> float:
    if not high_demand_missing:
        return 35.0
    vals = [float(x.get("demand_percentage") or 0) for x in high_demand_missing[:k]]
    return sum(vals) / max(1, len(vals))


def _weeks_for_hop(
    *,
    n_missing: int,
    avg_demand_missing: float,
    transition_obs_weight: int,
    probability: float,
) -> int:
    """More missing + harder demand → longer; more observed transitions → shorter path."""
    base = 3.0 + min(28.0, float(n_missing) * 1.35)
    demand_adj = 1.0 + min(0.95, max(0.0, avg_demand_missing) / 110.0)
    w = base * demand_adj
    if transition_obs_weight >= 4:
        w *= 0.88
    if transition_obs_weight >= 12:
        w *= 0.86
    if probability < 0.14:
        w *= 1.12
    if probability < 0.09:
        w *= 1.08
    return int(max(2, min(52, round(w))))


def _stagnation_risk(
    *,
    fit_pct: float,
    gap_pct: float,
    top_probability: float,
    n_high_miss: int,
    n_missing: int,
) -> float:
    r = 0.12
    r += max(0.0, (85.0 - fit_pct) / 220.0)
    r += max(0.0, (gap_pct - 40.0) / 350.0)
    r += max(0.0, (0.42 - top_probability) * 0.55)
    r += min(0.14, n_high_miss * 0.018)
    r += min(0.08, max(0, n_missing - 12) * 0.006)
    return round(max(0.05, min(0.92, r)), 3)


async def _edge_weight(session: AsyncSession, from_key: str, to_label: str) -> int:
    tk = normalize_role(to_label).strip().lower()
    row = await session.scalar(
        select(CareerTransitionStat.weight).where(
            CareerTransitionStat.from_role == from_key,
            CareerTransitionStat.to_role == tk,
        ).limit(1)
    )
    return int(row or 0)


async def predict_career_trajectory(
    session: AsyncSession,
    *,
    resume_id: int,
    target_role: str | None = None,
) -> dict:
    resume = await session.get(Resume, resume_id)
    if resume is None and is_ephemeral_resume_id(resume_id):
        row = get_live_resume_row(resume_id)
        if row:
            resume = SimpleNamespace(
                id=resume_id,
                raw_text=row.get("raw_text"),
                user_id=row.get("user_id"),
            )
    if not resume:
        raise ValueError(f"Resume {resume_id} not found")

    role_rows = await suggest_roles_from_corpus(session, resume_id)
    nr = normalize_role(target_role or "").strip().lower()
    if not nr and role_rows:
        nr = normalize_role(str(role_rows[0].get("role") or "")).strip().lower()
    if not nr:
        nr = "software engineer"

    display_current = nr.title() if nr.islower() else nr
    _, transitions = await weighted_next_roles(session, nr)
    if not transitions:
        # Fallback single hop from graph-less state
        return {
            "current_role": display_current,
            "likely_next_roles": [],
            "risk_of_stagnation": 0.45,
        }

    ms = MatchService(session)
    likely: list[dict] = []
    top_p = float(transitions[0]["probability"])

    for i, t in enumerate(transitions[:5]):
        role_name = str(t["role"])
        prob = float(t["probability"])
        if i < 3:
            gap_r = await ms.compute_resume_gap_for_role(resume_id, role_name)
            missing = gap_r.get("missing_skills") or []
            hd = gap_r.get("high_demand_missing_skills") or []
            n_miss = len(missing)
            avg_d = _avg_top_demand(hd if isinstance(hd, list) else [])
        else:
            n_miss = 6 + i * 2
            avg_d = 45.0

        tw = await _edge_weight(session, nr, role_name)
        weeks = _weeks_for_hop(
            n_missing=n_miss,
            avg_demand_missing=avg_d,
            transition_obs_weight=tw,
            probability=prob,
        )
        likely.append({
            "role": role_name,
            "probability": round(prob, 4),
            "time_estimate_weeks": weeks,
        })

    role_for_fit = nr.title() if nr.islower() else nr
    base_gap = await ms.compute_resume_gap_for_role(resume_id, role_for_fit)

    fit = float(base_gap.get("fit_percentage") or 0)
    gap_pct = float(base_gap.get("gap_percentage") or 0)
    hd_all = base_gap.get("high_demand_missing_skills") or []
    miss_all = base_gap.get("missing_skills") or []
    risk = _stagnation_risk(
        fit_pct=fit,
        gap_pct=gap_pct,
        top_probability=top_p,
        n_high_miss=len(hd_all) if isinstance(hd_all, list) else 0,
        n_missing=len(miss_all) if isinstance(miss_all, list) else 0,
    )

    return {
        "current_role": display_current,
        "likely_next_roles": likely,
        "risk_of_stagnation": risk,
    }
