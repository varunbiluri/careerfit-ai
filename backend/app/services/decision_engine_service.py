"""
Deterministic decision engine: best next action, ROI-ranked options, time-aware copy, decay heuristics.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume
from app.services.career_progress_service import (
    fetch_progress_series,
    improvement_rate_per_week,
    median_switch_weeks_hint,
    peer_improvement_percentile,
)
from app.services.normalization import normalize_role


def _effort_weeks_learn(demand_pct: float) -> float:
    """Higher market demand → slightly more competitive → more study time (bounded)."""
    return 2.0 + max(0.0, (85.0 - min(95.0, demand_pct))) / 22.0


def _roi_learn(projected_delta: float, demand_pct: float) -> float:
    gain = max(0.0, projected_delta) * (demand_pct / 100.0)
    effort = _effort_weeks_learn(demand_pct)
    return gain / max(0.75, effort)


def build_best_next_action(
    *,
    fit: float,
    projected_delta: float,
    high_demand_missing: list[dict],
    role_fits: list[dict],
    target_role: str,
    n_missing_total: int,
) -> dict[str, Any] | None:
    """
    ROI = (expected fit lift × demand weight) / effort_weeks — pick one action type.
    """
    target_n = normalize_role(target_role or "").strip().lower()
    best: tuple[float, dict[str, Any]] | None = None

    if high_demand_missing:
        top = high_demand_missing[0]
        sn = str(top.get("skill_name") or "")
        d = float(top.get("demand_percentage") or 40.0)
        roi = _roi_learn(projected_delta, d)
        impact = int(min(40, max(4, round(projected_delta * (d / 100.0)))))
        cand = {
            "type": "learn_skill",
            "reason": (
                f"Highest ROI right now: add {sn} (~{d:.0f}% demand weight in this slice) "
                f"with estimated ~{_effort_weeks_learn(d):.1f} weeks effort vs fit lift."
            ),
            "expected_impact_percent": impact,
            "detail_skill": sn,
        }
        best = (roi, cand)

    if len(role_fits) >= 2:
        r0 = role_fits[0]
        r1 = role_fits[1]
        name0 = str(r0.get("role") or "")
        f0 = float(r0.get("fit") or 0)
        f1 = float(r1.get("fit") or 0)
        n0 = normalize_role(name0).strip().lower()
        if n0 and n0 != target_n and (f0 - fit) >= 10:
            effort = 5.0
            gain = max(0.0, f0 - fit)
            roi_sw = (gain * 0.85) / effort
            cand = {
                "type": "switch_role",
                "reason": (
                    f"Corpus alignment for “{name0}” is ~{f0:.0f}% vs your current target slice ~{fit:.0f}% "
                    f"— pivoting target may unlock faster market match."
                ),
                "expected_impact_percent": int(min(45, max(8, round(gain * 0.65)))),
                "detail_role": name0,
            }
            if best is None or roi_sw > best[0]:
                best = (roi_sw, cand)

    if fit >= 58 and n_missing_total <= 5 and projected_delta < 12:
        effort = 1.5
        gain = min(18.0, 8.0 + (fit - 58) * 0.35)
        roi_ap = (gain * 0.55) / effort
        cand = {
            "type": "apply_jobs",
            "reason": (
                f"Fit is already ~{fit:.0f}% with few remaining gaps — prioritize applications and interview prep "
                f"while closing the last skills."
            ),
            "expected_impact_percent": int(round(gain)),
        }
        if best is None or roi_ap > best[0]:
            best = (roi_ap, cand)

    if best is None:
        return None
    return best[1]


def skill_decay_units(weekly_growth_pct: float | None, horizon_weeks: int) -> float:
    """
    Explainable decay proxy: max(0, −weekly_growth) × (horizon/8), capped.
    Interprets flat/negative posting trend as relevance pressure on that skill.
    """
    if weekly_growth_pct is None or weekly_growth_pct >= 0:
        return 0.0
    return min(18.0, abs(float(weekly_growth_pct)) * (horizon_weeks / 8.0))


def inaction_relevance_penalty_percent(
    growth_map: dict[str, float],
    resume_skills: list[str],
    horizon_weeks: int = 8,
) -> float:
    """Aggregate decay across negatively trending skills on the resume (capped)."""
    pen = 0.0
    n = 0
    for s in resume_skills[:35]:
        k = (s or "").strip().lower()
        if not k:
            continue
        g = float(growth_map.get(k, 0.0))
        if g < 0:
            pen += skill_decay_units(g, horizon_weeks)
            n += 1
    if n == 0:
        return 0.0
    return round(min(14.0, pen / math.sqrt(n)), 1)


def build_time_aware_insights(
    *,
    top_missing_names: list[str],
    demand_pcts: list[float],
    projected_delta: float,
) -> list[str]:
    lines: list[str] = []
    for name, d in zip(top_missing_names[:3], demand_pcts[:3]):
        w_lo = int(max(2, round(2 + (100 - d) / 40)))
        w_hi = int(min(16, w_lo + 2))
        pct = int(min(22, max(3, round(projected_delta * (d / 100.0)))))
        lines.append(
            f"If you learn {name} → about {w_lo}–{w_hi} weeks → ~+{pct}% estimated fit in this slice "
            f"(demand-weighted heuristic)."
        )
    return lines


def build_predictive_warnings(
    *,
    weakness_summary: list[str],
    likely_next_roles: list[dict],
    high_demand_missing: list[dict],
    fit: float,
) -> list[str]:
    warn: list[str] = []
    for w in weakness_summary:
        if "cloud" in w.lower():
            warn.append("You are falling behind on cloud skills relative to this market slice — prioritize one platform deeply.")
            break
    if likely_next_roles:
        top_p = float(likely_next_roles[0].get("probability") or 0)
        if top_p < 0.14 and len(likely_next_roles) >= 4:
            warn.append(
                "Your trajectory is split across many roles with no dominant next step — pick one target to reduce stagnation risk."
            )
    if high_demand_missing and fit < 55:
        top = high_demand_missing[0]
        sn = str(top.get("skill_name") or "")
        if sn:
            warn.append(
                f"Your current trajectory underserves high-demand gaps (e.g. {sn}) — without them, you drift toward lower-demand stacks."
            )
    return warn[:5]


def build_predictive_opportunities(
    *,
    role_fits: list[dict],
    projected_delta: float,
) -> list[str]:
    out: list[str] = []
    if len(role_fits) >= 1:
        r0 = str(role_fits[0].get("role") or "")
        f0 = float(role_fits[0].get("fit") or 0)
        if r0 and f0 >= 62:
            out.append(f"Your profile is trending toward “{r0}” (~{f0:.0f}% corpus alignment).")
    if projected_delta >= 10:
        out.append(
            f"Closing the highlighted gaps could add ~{int(projected_delta)}% estimated fit — one of the largest lifts we see in this slice."
        )
    return out[:4]


async def build_predictive_gap_bundle(
    session: AsyncSession,
    *,
    resume: Resume,
    gap: dict[str, Any],
    role_fits: list[dict],
    growth_map: dict[str, float],
    projected_delta: float,
    normalized_target: str,
    likely_next_roles: list[dict],
    weakness_summary: list[str],
) -> dict[str, Any]:
    """Single payload for ResumeGapOut predictive fields + career_insights extras."""
    fit = float(gap.get("fit_percentage") or 0)
    n_miss = len(gap.get("missing_skills") or [])
    hd = gap.get("high_demand_missing_skills") or []
    if not isinstance(hd, list):
        hd = []

    best = build_best_next_action(
        fit=fit,
        projected_delta=projected_delta,
        high_demand_missing=hd,
        role_fits=role_fits,
        target_role=normalized_target,
        n_missing_total=n_miss,
    )

    top_names = [str(x.get("skill_name") or "") for x in hd[:3]]
    top_d = [float(x.get("demand_percentage") or 45.0) for x in hd[:3]]
    time_lines = build_time_aware_insights(
        top_missing_names=top_names,
        demand_pcts=top_d,
        projected_delta=max(4.0, projected_delta),
    )

    months = 2
    horizon_w = int(round(months * 4.33))
    inaction_pen = inaction_relevance_penalty_percent(
        growth_map,
        list(gap.get("resume_skills") or []),
        horizon_weeks=horizon_w,
    )
    decay_lines: list[str] = []
    if inaction_pen >= 2.0:
        decay_lines.append(
            f"If you do nothing, negatively trending skills on your resume imply up to ~{inaction_pen:.0f}% "
            f"relative market relevance erosion over ~{months} months "
            f"(decay ≈ max(0, −weekly_demand_growth) × horizon; capped)."
        )

    decay_model_note = (
        "Per-skill decay uses weekly job-posting trend × horizon weeks (no ML); "
        "only skills with negative growth contribute."
    )

    warn = build_predictive_warnings(
        weakness_summary=weakness_summary,
        likely_next_roles=likely_next_roles,
        high_demand_missing=hd,
        fit=fit,
    )
    opp = build_predictive_opportunities(role_fits=role_fits, projected_delta=projected_delta)

    # Journey memory — peer improvement headline
    headline_improving = ""
    headline_trending = ""
    headline_switch = ""
    if resume.user_id is not None:
        series = await fetch_progress_series(session, user_id=resume.user_id, resume_id=resume.id, limit=80)
        rate = improvement_rate_per_week(series)
        peer_pct = peer_improvement_percentile(rate)
        if len(series) >= 3:
            headline_improving = (
                f"You are improving faster than about {peer_pct}% of users on our reference curve "
                f"(~{rate:+.2f} fit points/week across {len(series)} snapshots)."
            )
        switch_w = await median_switch_weeks_hint(session)
        headline_switch = (
            f"Most users with similar move patterns in our aggregate data show role-switch intent within ~{switch_w} weeks "
            "(heuristic from transition weights, not personalized job search data)."
        )

    if len(role_fits) >= 1:
        r0 = str(role_fits[0].get("role") or "")
        f0 = float(role_fits[0].get("fit") or 0)
        if r0:
            headline_trending = f"Embedding + market slice suggest your profile is trending toward “{r0}” (~{f0:.0f}% fit)."

    return {
        "best_next_action": best,
        "time_aware_insights": time_lines + decay_lines,
        "relevance_decay_model_note": decay_model_note,
        "predictive_warnings": warn,
        "predictive_opportunities": opp,
        "career_insights_extra": {
            "headline_improving_vs_peers": headline_improving,
            "headline_trending_role": headline_trending,
            "headline_switch_timing": headline_switch,
        },
    }
