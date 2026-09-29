from types import SimpleNamespace

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, JobSkill, Resume, ResumeSkill, Skill, UserProfile
from app.services.embedding_service import get_embeddings_async
from app.services.live_job_registry import (
    count_live,
    get_job as get_live_job,
    is_ephemeral_job_id,
)
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id
from app.services.skill_normalizer import normalize_skill_list
from app.services.career_stats_service import (
    compute_behavior_boost_points,
    compute_role_preference_boost_points,
    preference_skills_for_match,
)
from app.services.confidence_service import match_confidence
from app.services.skill_cluster_service import (
    collapse_skills_by_cluster,
    matched_missing_with_clusters,
    skill_to_canonical_map,
)
from app.services.normalization import expand_role_family, normalize_role
from app.services.skill_service import (
    filter_technical_skills_only,
    get_synthetic_market_for_role,
    get_synthetic_market_full,
    is_blocklisted_skill,
    is_high_demand_row_acceptable,
    is_plausible_skill_name,
    is_soft_skill,
    skill_demand_percentages,
    skill_demand_percentages_cached,
    skill_demand_percentages_for_title,
)

logger = get_logger(__name__)
# Max skills drawn from the role market slice (DB aggregate or live scrape batch).
MAX_JOBS = 50


def _synthetic_demand_pcts(n: int) -> list[float]:
    """
    Rank-based harmonic-decay weights for the synthetic fallback path (no real job data).
    Skill at rank 0 gets 1/1 weight, rank 1 gets 1/2, rank 2 gets 1/3, etc., normalised to 100.
    This avoids the misleading flat 100/n equal distribution (e.g. 5 skills → all 20%).
    """
    if n == 0:
        return []
    raw = [1.0 / (i + 1) for i in range(n)]
    total = sum(raw)
    return [round(r / total * 100.0, 2) for r in raw]


def _technical_reference_names(names: list[str]) -> list[str]:
    """Market / role reference skills with soft skills removed (cap MAX_JOBS)."""
    return filter_technical_skills_only(list(names))[:MAX_JOBS]


def _filter_live_jobs_for_role(
    live_jobs: list[dict[str, object]], job_title: str
) -> list[dict[str, object]]:
    """Keep jobs whose title matches the target role (substring, case-insensitive)."""
    role_raw = (job_title or "").strip()
    role_norm = normalize_role(role_raw) if role_raw else ""
    queries = expand_role_family(role_norm or role_raw) or ([role_raw] if role_raw else [])
    queries = [q for q in queries if q and str(q).strip()]
    if not queries:
        return list(live_jobs)
    out: list[dict[str, object]] = []
    for j in live_jobs:
        title = (j.get("title") or "")
        if not isinstance(title, str):
            title = str(title)
        tl = title.lower()
        if any(str(q).strip().lower() in tl for q in queries):
            out.append(j)
    return out if out else list(live_jobs)


def _build_live_skill_demand(
    jobs: list[dict[str, object]],
) -> list[tuple[str, int, float]]:
    """
    Demand stats from the current scrape batch only (weighted like DB: each job weight 1.0).
    Returns rows (skill_name, weighted_job_hits, demand_pct) sorted by hits descending.
    """
    total_w = float(len(jobs))
    if total_w <= 0:
        return []
    skill_weight: dict[str, float] = {}
    for j in jobs:
        raw_skills = j.get("skills") or j.get("skill_names") or []
        if not isinstance(raw_skills, list):
            continue
        skills = normalize_skill_list([str(x) for x in raw_skills if x])
        seen: set[str] = set()
        for s in skills:
            sl = (s or "").strip().lower()
            if not sl or sl in seen:
                continue
            if is_soft_skill(s):
                continue
            seen.add(sl)
            skill_weight[s] = skill_weight.get(s, 0.0) + 1.0
    rows: list[tuple[str, int, float]] = []
    for name, sw in skill_weight.items():
        pct = round((sw / total_w) * 100.0, 2) if total_w > 0 else 0.0
        rows.append((name, int(round(sw)), pct))
    rows.sort(key=lambda x: -x[1])
    return rows


def demand_by_name_from_live_registry(limit: int = 200) -> dict[str, dict]:
    """Global skill demand from in-memory scraped jobs only (same shape as skill_demand_percentages_cached)."""
    from app.services.live_job_registry import list_jobs as list_live_jobs

    rows = list_live_jobs(limit)
    jobs = [{"skills": j.get("skills") or j.get("skill_names") or []} for j in rows]
    demand_rows = _build_live_skill_demand(jobs)
    return {
        r[0]: {"id": 0, "name": r[0], "category": None, "count": r[1], "pct": r[2]}
        for r in demand_rows
        if not is_soft_skill(r[0])
    }


def market_names_for_role_live(role: str, limit: int = 200) -> list[str]:
    """Top market skills for a role from live registry (role-filtered, then full registry if empty)."""
    from app.services.live_job_registry import list_jobs as list_live_jobs

    rows = list_live_jobs(limit)
    corpus = [
        {"title": r.get("title"), "skills": r.get("skill_names") or r.get("skills") or []}
        for r in rows
    ]
    filtered = _filter_live_jobs_for_role(corpus, role)
    dr = _build_live_skill_demand(
        [{"skills": j.get("skills") or j.get("skill_names") or []} for j in filtered]
    )
    if not dr and rows:
        dr = _build_live_skill_demand(
            [{"skills": r.get("skill_names") or r.get("skills") or []} for r in rows]
        )
    raw = [r[0] for r in dr[:MAX_JOBS * 2]]
    return _technical_reference_names(raw)


CONF_TEMPLATES: dict[str, list[str]] = {
    "high": [
        "Insights are based on high-quality, detailed job data.",
        "Analysis uses reliable and detailed job listings.",
    ],
    "moderate": [
        "Insights are based on partially available job data and may vary slightly.",
        "Analysis uses partially available job data; some variability is expected.",
    ],
    "low": [
        "Insights rely on limited or fallback data; recommendations are indicative.",
        "Analysis is based on limited data and should be interpreted cautiously.",
    ],
}

WEIGHT_SEMANTIC = 0.50
WEIGHT_SKILL_OVERLAP = 0.30
WEIGHT_KEYWORD = 0.20
WEIGHT_DEMAND_PENALTY = 0.20


def _sanitize_gap_fit(
    fit: float,
    gap: float,
    n_resume_skills: int,
    db_job_count: int,
) -> tuple[float, float]:
    """Avoid misleading 0% / 100% gap when the resume is non-empty or DB has no jobs."""
    if n_resume_skills >= 6 and fit < 8.0 and gap > 92.0:
        # Blend raw overlap with resume breadth so scores differ by role/market slice;
        # the old linear cap hit 78% for almost any large skill list.
        breadth = min(n_resume_skills, 40) * 0.65
        nf = float(np.clip(24.0 + 0.72 * fit + breadth, 26.0, 88.0))
        return round(nf, 2), round(100.0 - nf, 2)
    if db_job_count == 0 and n_resume_skills >= 3:
        nf = float(np.clip(30.0 + n_resume_skills * 3.5, 25.0, 72.0))
        return round(nf, 2), round(100.0 - nf, 2)
    return fit, gap


def _clamp_display_fit(fit: float, gap: float) -> tuple[float, float]:
    """Clamp market fit to [20, 95] so scores stay interpretable (UX + research demos)."""
    cf = float(np.clip(fit, 20.0, 95.0))
    return round(cf, 2), round(100.0 - cf, 2)


def _clamp_match_score(score: float) -> float:
    return float(np.clip(score, 20.0, 95.0))


def safe_score(value) -> float:
    """Defensive score cast used only for nullable/fallback values."""
    try:
        v = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(100.0, v))


def _demand_penalty_multiplier(job_source: str | None) -> float:
    """Downweight demand D when market is synthetic or curated corpus-only."""
    if not job_source:
        return 1.0
    s = job_source.lower()
    if s == "synthetic_fallback":
        return 0.5
    if s == "corpus":
        return 0.75
    return 1.0


def _fallback_match_total_score(n_resume_skills: int, semantic_score_0_100: float) -> float:
    base = 32.0 + min(38.0, n_resume_skills * 2.8)
    sem_boost = max(0.0, semantic_score_0_100 - 35.0) * 0.25
    return float(np.clip(base + sem_boost, 28.0, 82.0))


def _cosine_sim(vec1: list[float], vec2: list[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    a = np.array(vec1).reshape(1, -1)
    b = np.array(vec2).reshape(1, -1)
    return float(np.clip(cosine_similarity(a, b)[0, 0], 0.0, 1.0))


# Embedding input caps (context + demo latency)
_JOB_EMB_TEXT_MAX = 2000
_RESUME_EMB_TEXT_MAX = 3000


def _keyword_overlap_semantic(job_skills: set[str], resume_lower: str) -> float:
    """Deterministic proxy when embeddings are unavailable (keyword coverage of required skills)."""
    if not job_skills:
        return 0.25
    hits = 0
    for s in job_skills:
        sl = (s or "").strip().lower()
        if sl and sl in resume_lower:
            hits += 1
    return float(min(1.0, max(0.05, (hits / max(1, len(job_skills))) * 0.92 + 0.04)))


async def _matched_missing(
    reference_names: list[str], candidate_names: list[str]
) -> tuple[list[str], list[str]]:
    ref = normalize_skill_list(list(reference_names))
    cand = normalize_skill_list(list(candidate_names))
    settings = get_settings()
    if getattr(settings, "use_semantic_skill_matching", False):
        thr = getattr(settings, "skill_cluster_similarity_threshold", 0.85)
        matched, missing = await matched_missing_with_clusters(ref, cand, threshold=thr)
    else:
        ref_set = set(ref)
        cand_set = set(cand)
        matched = sorted(ref_set & cand_set)
        missing = sorted(ref_set - cand_set)
    # Hard guard: any skill present in the candidate (resume) set must not be classified as missing.
    cand_set = set(cand)
    missing = [s for s in missing if s not in cand_set]
    return matched, missing


def _compute_uncertainty(n_job_skills: int) -> float:
    """
    Honest uncertainty heuristic (0–30, lower = more confident).
    More reference skills → lower uncertainty; replaces the invalid SE=3/sqrt(n) CI.
    """
    if n_job_skills == 0:
        return 30.0
    return round(min(30.0, 30.0 / (n_job_skills ** 0.5)), 2)


def _build_score_factors(
    semantic: float,
    overlap: float,
    keyword: float,
    matched: list[str],
    missing: list[str],
    demand_by_name: dict,
    demand_penalty_points: float,
) -> tuple[list[str], list[str]]:
    """
    Return (top_positive_factors, top_negative_factors) for explainable scoring.
    demand_by_name values are now dicts {"id", "name", "category", "count", "pct"}.
    """
    positives: list[str] = []
    negatives: list[str] = []

    if semantic >= 70:
        positives.append(f"High semantic similarity ({semantic:.0f}%)")
    elif semantic >= 50:
        positives.append(f"Moderate semantic alignment ({semantic:.0f}%)")

    if overlap >= 70:
        positives.append(f"Strong skill coverage ({overlap:.0f}% of required skills matched)")
    elif overlap >= 50:
        positives.append(f"Partial skill coverage ({overlap:.0f}% of required skills matched)")

    if keyword >= 70:
        positives.append(f"Good keyword coverage in resume text ({keyword:.0f}%)")

    if matched:
        sample = ", ".join(sorted(matched)[:3])
        positives.append(f"Matched required skills: {sample}")

    if semantic < 50:
        negatives.append(f"Low semantic similarity ({semantic:.0f}%) — resume language diverges from job description")

    if overlap < 50:
        negatives.append(f"Skill gap: only {overlap:.0f}% of required skills matched")

    if missing:
        # demand_by_name values are dicts; use ["pct"] not tuple index [2]
        high_demand = sorted(
            [s for s in missing if s in demand_by_name],
            key=lambda x: -demand_by_name[x]["pct"],
        )[:3]
        if high_demand:
            negatives.append(f"Missing high-demand skills: {', '.join(high_demand)}")
        elif missing[:3]:
            negatives.append(f"Missing required skills: {', '.join(missing[:3])}")

    if demand_penalty_points > 5:
        negatives.append(f"Demand penalty ({demand_penalty_points:.1f} pts) for absent high-demand skills")

    return positives[:4], negatives[:4]


def _generate_score_reason(
    semantic: float,
    overlap: float,
    keyword: float,
    demand_penalty_points: float,
    missing: list[str],
    demand_by_name: dict,
) -> str:
    """One-sentence explanation of the dominant score drivers.
    demand_by_name values are dicts; use ["pct"] not tuple index [2].
    """
    reasons: list[str] = []

    if overlap < 30:
        top_m = sorted(
            [s for s in missing if s in demand_by_name],
            key=lambda x: -demand_by_name[x]["pct"],
        )[:3]
        if top_m:
            reasons.append(f"Low skill overlap; missing high-demand: {', '.join(top_m)}")
        else:
            reasons.append("Low skill overlap with job requirements")

    if semantic < 30:
        reasons.append("Low semantic similarity between resume and job description")

    if demand_penalty_points > 10:
        top_d = sorted(
            [s for s in missing if s in demand_by_name],
            key=lambda x: -demand_by_name[x]["pct"],
        )[:3]
        if top_d:
            reasons.append(f"Penalized for high-demand absent skills: {', '.join(top_d)}")

    if not reasons:
        if semantic > 60 and overlap > 60:
            return "Strong alignment across semantic similarity and skill overlap"
        if keyword > 60:
            return "Good keyword coverage; improve skill overlap to increase score"
        return "Moderate fit — expand skill coverage to increase score"

    return "; ".join(reasons)


class MatchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def count_jobs_total(self) -> int:
        n = (await self.session.execute(select(func.count(Job.id)))).scalar()
        return int(n or 0)

    async def get_job_skill_names(self, job_id: int) -> list[str]:
        if is_ephemeral_job_id(job_id):
            row = get_live_job(job_id)
            if not row:
                return []
            return normalize_skill_list(list(row.get("skill_names") or []))
        stmt = (
            select(Skill.name)
            .join(JobSkill, JobSkill.skill_id == Skill.id)
            .where(JobSkill.job_id == job_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_resume_skill_names(self, resume_id: int) -> list[str]:
        if is_ephemeral_resume_id(resume_id):
            row = get_live_resume_row(resume_id)
            if not row:
                return []
            return normalize_skill_list(list(row.get("skill_names") or []))
        stmt = (
            select(Skill.name)
            .join(ResumeSkill, ResumeSkill.skill_id == Skill.id)
            .where(ResumeSkill.resume_id == resume_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def compute_match(self, job_id: int, resume_id: int, include_demand: bool = True) -> dict:
        job_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_job_skill_names(job_id))
        )
        resume_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_resume_skill_names(resume_id))
        )
        if not resume_skills:
            resume_skills = ["python"]
        matched, missing = await _matched_missing(
            reference_names=job_skills, candidate_names=resume_skills
        )
        # Double guard in scoring layer: resume skills must never remain in missing.
        candidate_skills = set(resume_skills)
        missing = [s for s in missing if s not in candidate_skills]
        missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
        job_set = set(job_skills)
        match_pct = (len(matched) / len(job_set) * 100.0) if job_set else 100.0

        job = await self.session.get(Job, job_id)
        if job is None and is_ephemeral_job_id(job_id):
            erow = get_live_job(job_id)
            if erow:
                job = SimpleNamespace(
                    id=job_id,
                    external_id=erow["external_id"],
                    title=erow.get("title"),
                    company=erow.get("company"),
                    description=erow.get("description") or "",
                    url=erow.get("url"),
                    source=erow.get("source") or "scraped",
                )
        resume = await self.session.get(Resume, resume_id)
        if resume is None and is_ephemeral_resume_id(resume_id):
            er = get_live_resume_row(resume_id)
            if er:
                resume = SimpleNamespace(
                    id=resume_id,
                    raw_text=er.get("raw_text"),
                    user_id=er.get("user_id"),
                )
        job_text = (job.description or job.title or "") if job else ""
        resume_text = (resume.raw_text or "") if resume else ""
        resume_lower = resume_text.lower()

        semantic_sim = 0.0
        if job_text.strip() and resume_text.strip():
            jt = job_text[:_JOB_EMB_TEXT_MAX]
            rt = resume_text[:_RESUME_EMB_TEXT_MAX]
            try:
                embs = await get_embeddings_async([jt, rt])
                if len(embs) >= 2 and embs[0] and embs[1]:
                    semantic_sim = _cosine_sim(embs[0], embs[1])
                else:
                    semantic_sim = _keyword_overlap_semantic(job_set, resume_lower)
                    logger.info(
                        "match keyword semantic fallback job_id=%s resume_id=%s",
                        job_id,
                        resume_id,
                    )
            except Exception as exc:
                logger.warning(
                    "match embeddings failed job_id=%s resume_id=%s: %s",
                    job_id,
                    resume_id,
                    exc,
                )
                semantic_sim = _keyword_overlap_semantic(job_set, resume_lower)

        semantic_score = safe_score(semantic_sim * 100.0)

        db_jobs = await self.count_jobs_total()
        live_n = count_live()
        settings = get_settings()
        live_only = bool(getattr(settings, "live_market_only", False))
        no_market = (live_n == 0) if live_only else (db_jobs == 0 and live_n == 0)
        profile = None
        if resume and resume.user_id:
            profile = (
                await self.session.execute(
                    select(UserProfile).where(UserProfile.user_id == resume.user_id),
                )
            ).scalar_one_or_none()

        if no_market:
            est = _fallback_match_total_score(len(resume_skills), semantic_score)
            match_pct_fb = safe_score(round(est, 2))
            match_pct_fb = _clamp_match_score(match_pct_fb)
            pref_fb = await preference_skills_for_match(
                self.session, resume_id, profile.preferred_skills if profile else None,
            )
            beh_fb, _ = compute_behavior_boost_points(job_skills, pref_fb)
            role_fb, role_r_fb = compute_role_preference_boost_points(
                job.title if job else None,
                profile.preferred_roles if profile else None,
            )
            match_pct_fb = _clamp_match_score(min(100.0, match_pct_fb + beh_fb + role_fb))
            conf_fb = match_confidence(
                db_job_count=0,
                uncertainty_score=25.0,
                semantic_similarity=semantic_sim,
                n_job_skills=len(job_set),
            )
            why_fb = [
                "Why? No aggregated job corpus — score is a text-similarity estimate vs this job description.",
            ]
            if beh_fb:
                why_fb.append("Why? Boost from skills seen in jobs you clicked or applied to.")
            if role_r_fb:
                why_fb.append(f"Why? {role_r_fb}")
            return {
                "job_id": job_id,
                "job_external_id": job.external_id if job else "",
                "job_title": job.title if job else None,
                "match_percentage": match_pct_fb,
                "match_mode": "fallback",
                "resume_score": {
                    "total_score": match_pct_fb,
                    "semantic_score": round(semantic_score, 2),
                    "skill_overlap_score": round(match_pct_fb, 2),
                    "keyword_coverage_score": round(match_pct_fb, 2),
                    "weights_used": {
                        "semantic": WEIGHT_SEMANTIC,
                        "skill_overlap": WEIGHT_SKILL_OVERLAP,
                        "keyword_coverage": WEIGHT_KEYWORD,
                        "demand_penalty": WEIGHT_DEMAND_PENALTY,
                    },
                    "demand_penalty_raw": 0.0,
                    "demand_penalty_points": 0.0,
                    "uncertainty_score": 25.0,
                    "score_reason": "Estimated match — no aggregated job corpus in database",
                    "projected_total_score": None,
                    "projection_message": None,
                    "scoring_mode": "fallback",
                    "scoring_reason": "no_market_data",
                    "behavior_boost": beh_fb,
                    "behavior_score_normalized": round(beh_fb / 100.0, 4),
                    "base_score_before_behavior": None,
                    "profile_role_boost": role_fb,
                    "confidence": conf_fb,
                    "why_lines": why_fb,
                },
                "matched_skills": matched,
                "missing_skills": missing,
                "semantic_similarity": round(semantic_sim, 4),
                "high_demand_missing_skills": [],
                "missing_skill_impacts": [],
                "top_positive_factors": ["Estimated from resume ↔ job text (market data unavailable)"],
                "top_negative_factors": [],
                "match_explanation": (
                    "No live scraped jobs in memory yet — estimate from resume vs job text only."
                    if live_only
                    else "No job corpus in DB — estimate from resume vs job text only."
                ),
                "confidence": conf_fb,
            }
        skill_overlap_score = (len(matched) / len(job_set) * 100.0) if job_set else 100.0
        resume_text_lower = resume_text.lower()
        keyword_hits = sum(1 for s in job_set if s.lower() in resume_text_lower)
        keyword_coverage_score = (keyword_hits / len(job_set) * 100.0) if job_set else 100.0
        skill_overlap_score = safe_score(skill_overlap_score)
        keyword_coverage_score = safe_score(keyword_coverage_score)

        high_demand_missing: list[dict] = []
        # demand_by_name maps skill name → dict {"id","name","category","count","pct"}
        demand_by_name: dict[str, dict] = {}
        if getattr(settings, "use_semantic_skill_matching", False) and missing:
            cmap = await skill_to_canonical_map(
                list(job_set | set(resume_skills) | set(missing)),
            )
            if include_demand:
                if live_only:
                    demand_by_name = demand_by_name_from_live_registry()
                else:
                    demand_list = await skill_demand_percentages_cached(self.session)
                    demand_by_name = {
                        d["name"]: d for d in demand_list if not is_soft_skill(d["name"])
                    }
                dw = {
                    m: float(demand_by_name[m]["pct"])
                    for m in missing
                    if m in demand_by_name
                }
                missing = collapse_skills_by_cluster(
                    missing, cmap, demand_key=dw if dw else None,
                )
            else:
                missing = collapse_skills_by_cluster(missing, cmap, demand_key=None)
        if include_demand and missing:
            if not demand_by_name:
                if live_only:
                    demand_by_name = demand_by_name_from_live_registry()
                else:
                    demand_list = await skill_demand_percentages_cached(self.session)
                    demand_by_name = {
                        d["name"]: d for d in demand_list if not is_soft_skill(d["name"])
                    }
            for skill_name in missing:
                if is_blocklisted_skill(skill_name) or not is_plausible_skill_name(skill_name):
                    continue
                if skill_name in demand_by_name:
                    d = demand_by_name[skill_name]
                    high_demand_missing.append({
                        "skill_id": d["id"],
                        "skill_name": d["name"],
                        "category": d["category"],
                        "job_count": d["count"],
                        "demand_percentage": d["pct"],
                    })
        high_demand_missing.sort(key=lambda x: -x["demand_percentage"])

        # Demand penalty: use mean of top-5 highest-demand missing skills.
        # Previously used mean of ALL missing skills; averaging over many
        # low-demand skills diluted the signal from the genuinely critical gaps.
        # Top-5 preserves the same 0-100 scale for D so existing score range
        # (clipped 0-100) is unchanged.
        demand_pcts_sorted = sorted(
            [float(demand_by_name[s]["pct"]) for s in missing if s in demand_by_name],
            reverse=True,
        )[:5]
        D = float(np.mean(demand_pcts_sorted)) if demand_pcts_sorted else 0.0
        d_mult = _demand_penalty_multiplier(job.source if job else None)
        market_n = live_n if live_only else db_jobs
        if market_n < 25:
            d_mult *= 0.9
        D_effective = D * d_mult
        demand_penalty_points = WEIGHT_DEMAND_PENALTY * D_effective
        base_total = float(np.clip(
            WEIGHT_SEMANTIC * semantic_score
            + WEIGHT_SKILL_OVERLAP * skill_overlap_score
            + WEIGHT_KEYWORD * keyword_coverage_score
            - demand_penalty_points,
            0.0, 100.0,
        ))
        base_total = _clamp_match_score(base_total)
        match_pct = _clamp_match_score(match_pct)

        pref_skills = await preference_skills_for_match(
            self.session, resume_id, profile.preferred_skills if profile else None,
        )
        beh_pts, beh_reason = compute_behavior_boost_points(job_skills, pref_skills)
        role_pts, role_reason = compute_role_preference_boost_points(
            job.title if job else None, profile.preferred_roles if profile else None,
        )
        total_score = _clamp_match_score(min(100.0, base_total + beh_pts + role_pts))
        match_pct = _clamp_match_score(min(100.0, match_pct + beh_pts + role_pts))
        degraded_mult = 1.0
        if job and (
            bool(getattr(job, "is_degraded", False))
            or ((job.source or "").lower() == "scraped" and len((job.description or "").strip()) < 200)
        ):
            degraded_mult = 0.8
        # Apply quality scaling only at the final stage so formula structure remains unchanged.
        total_score = _clamp_match_score(min(100.0, degraded_mult * total_score))
        match_pct = _clamp_match_score(min(100.0, degraded_mult * match_pct))

        confidence_simple = min(1.0, len(matched) / (len(job_set) + 1))

        why_lines = [
            (
                f"Why? {WEIGHT_SEMANTIC:.0%}×semantic ({semantic_score:.0f}%) + "
                f"{WEIGHT_SKILL_OVERLAP:.0%}×skill overlap ({skill_overlap_score:.0f}%) + "
                f"{WEIGHT_KEYWORD:.0%}×keywords ({keyword_coverage_score:.0f}%) − demand penalty "
                f"(~{D:.1f}% avg on top missing → {demand_penalty_points:.1f} pts)."
            ),
        ]
        if beh_reason:
            why_lines.append(f"Why? {beh_reason}")
        if role_reason:
            why_lines.append(f"Why? {role_reason}")

        def _has_similar_line(text: str) -> bool:
            t = text.lower()
            return any(
                (t in (w or "").lower()) or ((w or "").lower() in t)
                for w in why_lines
                if w
            )

        def _append_why_once(text: str) -> bool:
            if not text or _has_similar_line(text):
                return False
            why_lines.append(text)
            return True

        data_confidence = 1.0
        if job and (
            bool(getattr(job, "is_degraded", False))
            or ((job.source or "").lower() == "scraped" and len((job.description or "").strip()) < 200)
        ):
            data_confidence = 0.6
        if job and getattr(job, "source", "") in ("synthetic_fallback", "corpus"):
            data_confidence = 0.3

        if data_confidence >= 0.85:
            conf_label = "high"
        elif data_confidence >= 0.5:
            conf_label = "moderate"
        else:
            conf_label = "low"
        # Deterministic template choice so phrasing varies without run-to-run drift.
        seed_val = (int(job_id) * 31 + int(resume_id) * 17) % 1000
        choices = CONF_TEMPLATES.get(conf_label) or CONF_TEMPLATES["moderate"]
        conf_msg = choices[seed_val % len(choices)]

        # Add at most 3 enhancement lines in priority order.
        extra_added = 0
        if _append_why_once(f"Why? Data confidence: {conf_label} — {conf_msg}"):
            extra_added += 1
        if matched and extra_added < 3:
            sample = ", ".join(sorted(matched)[:3])
            if _append_why_once(
                f"You match {skill_overlap_score:.0f}% of required skills, primarily aligned with {sample}."
            ):
                extra_added += 1
        if extra_added < 3:
            if missing:
                top_missing = ", ".join(sorted(missing)[:3])
                _append_why_once(
                    f"You can strengthen your profile by improving skills like {top_missing}."
                )
            else:
                _append_why_once(
                    "Analysis combines live job market data and curated industry benchmarks."
                )

        n_job = len(job_set)
        uncertainty_score = _compute_uncertainty(n_job)
        if (live_n if live_only else db_jobs) < 30:
            uncertainty_score = min(30.0, uncertainty_score + 8.0)
        if job and job.source in ("synthetic_fallback", "corpus"):
            uncertainty_score = min(30.0, uncertainty_score + 5.0)
        score_reason = _generate_score_reason(
            semantic_score, skill_overlap_score, keyword_coverage_score,
            demand_penalty_points, missing, demand_by_name,
        )
        if beh_pts > 0 and score_reason:
            score_reason = score_reason + f" Behavior boost +{beh_pts:.1f} from jobs you engaged with."
        if role_pts > 0 and score_reason:
            score_reason = score_reason + f" Profile role boost +{role_pts:.1f}."
        top_positive_factors, top_negative_factors = _build_score_factors(
            semantic_score, skill_overlap_score, keyword_coverage_score,
            matched, missing, demand_by_name, demand_penalty_points,
        )

        score_drop_per_skill = (100.0 * (WEIGHT_SKILL_OVERLAP + WEIGHT_KEYWORD) / n_job) if n_job else 0.0
        missing_skill_impacts: list[dict] = []
        for skill_name in missing:
            demand_pct = demand_by_name.get(skill_name)
            # demand_pct is now a dict, not a tuple; use ["pct"] key
            demand_percentage = float(demand_pct["pct"]) if demand_pct is not None else None
            demand_penalty_impact = (
                round(score_drop_per_skill * (demand_percentage / 100.0), 2)
                if demand_percentage is not None else None
            )
            # D_new = hypothetical penalty if this skill were added; apply same
            # top-5 selection as the main D calculation for consistency
            D_new_pcts = sorted(
                [float(demand_by_name[s]["pct"]) for s in missing if s != skill_name and s in demand_by_name],
                reverse=True,
            )[:5]
            D_new = float(np.mean(D_new_pcts)) if D_new_pcts else 0.0
            score_if_added = float(np.clip(
                round(total_score + score_drop_per_skill + WEIGHT_DEMAND_PENALTY * d_mult * (D - D_new), 2),
                0.0, 100.0,
            ))
            missing_skill_impacts.append({
                "skill_name": skill_name,
                "score_drop": round(score_drop_per_skill, 2),
                "score_if_added": score_if_added,
                "demand_percentage": demand_percentage,
                "demand_penalty_impact": demand_penalty_impact,
            })

        top_impacts = sorted(
            missing_skill_impacts,
            key=lambda x: float(x.get("score_drop") or 0),
            reverse=True,
        )[:5]
        gain_top5 = sum(float(x.get("score_drop") or 0) for x in top_impacts)
        projected_total = float(np.clip(total_score + gain_top5, 0.0, 100.0))
        projection_message: str | None = None
        projected_out: float | None = None
        if projected_total > total_score + 0.5:
            projected_out = round(projected_total, 2)
            projection_message = f"If you learn top skills → ~{projected_total:.0f}% fit"

        conf_lbl = match_confidence(
            db_job_count=live_n if live_only else db_jobs,
            uncertainty_score=uncertainty_score,
            semantic_similarity=semantic_sim,
            n_job_skills=n_job,
        )

        resume_score_payload = {
            "total_score": round(total_score, 2),
            "semantic_score": round(semantic_score, 2),          # fixed: was overwritten by skill_overlap_score
            "skill_overlap_score": round(skill_overlap_score, 2),
            "keyword_coverage_score": round(keyword_coverage_score, 2),
            "weights_used": {
                "semantic": WEIGHT_SEMANTIC,
                "skill_overlap": WEIGHT_SKILL_OVERLAP,
                "keyword_coverage": WEIGHT_KEYWORD,
                "demand_penalty": WEIGHT_DEMAND_PENALTY,
            },
            "demand_penalty_raw": round(D, 2),
            "demand_penalty_points": round(-demand_penalty_points, 2),
            "uncertainty_score": uncertainty_score,
            "score_reason": score_reason,
            "projected_total_score": projected_out,
            "projection_message": projection_message,
            "behavior_boost": beh_pts,
            "behavior_score_normalized": round(beh_pts / 100.0, 4),
            "base_score_before_behavior": round(base_total, 2) if beh_pts > 0 or role_pts > 0 else None,
            "profile_role_boost": role_pts,
            "confidence": conf_lbl,
            "why_lines": why_lines,
        }
        logger.info(
            "match_event %s",
            {
                "event": "match_compute",
                "job_id": job_id,
                "resume_id": resume_id,
                "job_skills_count": len(job_set),
                "matched_count": len(matched),
                "missing_count": len(missing),
                "fallback_used": no_market,
            },
        )

        return {
            "job_id": job_id,
            "job_external_id": job.external_id if job else "",
            "job_title": job.title if job else None,
            "match_percentage": round(match_pct, 2),
            "match_mode": "live",
            "confidence": conf_lbl,
            "resume_score": resume_score_payload,
            "matched_skills": matched,
            "missing_skills": missing,
            "semantic_similarity": round(semantic_sim, 4),
            "high_demand_missing_skills": high_demand_missing,
            "missing_skill_impacts": missing_skill_impacts,
            "top_positive_factors": top_positive_factors,
            "top_negative_factors": top_negative_factors,
            "match_explanation": " ".join(why_lines),
        }

    async def compute_resume_gap(self, resume_id: int) -> dict:
        resume_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_resume_skill_names(resume_id))
        )
        db_jobs = await self.count_jobs_total()
        live_n = count_live()
        if get_settings().live_market_only:
            demand_by_name = demand_by_name_from_live_registry()
            if not demand_by_name:
                fit, gap = _sanitize_gap_fit(100.0, 0.0, len(resume_skills), live_n)
                fit, gap = _clamp_display_fit(fit, gap)
                return {
                    "resume_skills": resume_skills,
                    "market_skill_count": 0,
                    "matched_skills": [],
                    "missing_skills": [],
                    "high_demand_missing_skills": [],
                    "fit_percentage": fit,
                    "gap_percentage": gap,
                    "market_source": "live_corpus",
                }
            market_names = _technical_reference_names(list(demand_by_name.keys()))
            market_set = set(market_names)
            matched, missing = await _matched_missing(
                reference_names=market_names, candidate_names=resume_skills
            )
            candidate_skills = set(resume_skills)
            missing = [s for s in missing if s not in candidate_skills]
            missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
            high_demand_missing: list[dict] = []
            for skill_name in missing:
                if skill_name in demand_by_name:
                    d = demand_by_name[skill_name]
                    high_demand_missing.append({
                        "skill_id": d["id"],
                        "skill_name": d["name"],
                        "category": d["category"],
                        "job_count": d["count"],
                        "demand_percentage": d["pct"],
                    })
            high_demand_missing.sort(key=lambda x: -x["demand_percentage"])
            raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
            fit, gap = _sanitize_gap_fit(
                round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), live_n
            )
            fit, gap = _clamp_display_fit(fit, gap)
            return {
                "resume_skills": resume_skills,
                "market_skill_count": len(market_set),
                "matched_skills": matched,
                "missing_skills": missing,
                "high_demand_missing_skills": high_demand_missing,
                "fit_percentage": fit,
                "gap_percentage": gap,
                "market_source": "live_corpus",
            }
        # skill_demand_percentages_cached returns list[dict] now (not ORM tuples)
        demand_list = await skill_demand_percentages_cached(self.session)
        if not demand_list:
            market_names = _technical_reference_names(get_synthetic_market_full()[: MAX_JOBS * 2])
            if not market_names:
                fit, gap = _sanitize_gap_fit(100.0, 0.0, len(resume_skills), db_jobs)
                fit, gap = _clamp_display_fit(fit, gap)
                return {
                    "resume_skills": resume_skills,
                    "market_skill_count": 0,
                    "matched_skills": [],
                    "missing_skills": [],
                    "high_demand_missing_skills": [],
                    "fit_percentage": fit,
                    "gap_percentage": gap,
                    "market_source": "synthetic",
                }
            market_set = set(market_names)
            matched, missing = await _matched_missing(
                reference_names=market_names, candidate_names=resume_skills
            )
            candidate_skills = set(resume_skills)
            missing = [s for s in missing if s not in candidate_skills]
            missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
            _synth_pcts = _synthetic_demand_pcts(len(missing))
            high_demand_missing = [
                {"skill_id": 0, "skill_name": s, "category": None, "job_count": 0,
                 "demand_percentage": _synth_pcts[i]}
                for i, s in enumerate(missing)
            ]
            raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
            fit, gap = _sanitize_gap_fit(
                round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), db_jobs
            )
            fit, gap = _clamp_display_fit(fit, gap)
            return {
                "resume_skills": resume_skills,
                "market_skill_count": len(market_set),
                "matched_skills": matched,
                "missing_skills": missing,
                "high_demand_missing_skills": high_demand_missing,
                "fit_percentage": fit,
                "gap_percentage": gap,
                "market_source": "synthetic",
            }
        # demand_list is list[dict] — extract names for matching
        market_names = _technical_reference_names([d["name"] for d in demand_list])
        market_set = set(market_names)
        matched, missing = await _matched_missing(
            reference_names=market_names, candidate_names=resume_skills
        )
        candidate_skills = set(resume_skills)
        missing = [s for s in missing if s not in candidate_skills]
        missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
        demand_by_name: dict[str, dict] = {
            d["name"]: d for d in demand_list if not is_soft_skill(d["name"])
        }
        high_demand_missing: list[dict] = []
        for skill_name in missing:
            if skill_name in demand_by_name:
                d = demand_by_name[skill_name]
                high_demand_missing.append({
                    "skill_id": d["id"],
                    "skill_name": d["name"],
                    "category": d["category"],
                    "job_count": d["count"],
                    "demand_percentage": d["pct"],
                })
        high_demand_missing.sort(key=lambda x: -x["demand_percentage"])
        raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
        fit, gap = _sanitize_gap_fit(
            round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), db_jobs
        )
        fit, gap = _clamp_display_fit(fit, gap)
        return {
            "resume_skills": resume_skills,
            "market_skill_count": len(market_set),
            "matched_skills": matched,
            "missing_skills": missing,
            "high_demand_missing_skills": high_demand_missing,
            "fit_percentage": fit,
            "gap_percentage": gap,
            "market_source": "scraped",
        }

    async def _empty_role_gap_live(self, resume_id: int) -> dict:
        """No live jobs / no extractable skills — avoid DB market aggregates when live_market_only."""
        resume_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_resume_skill_names(resume_id))
        )
        mj = count_live()
        fit, gap = _sanitize_gap_fit(100.0, 0.0, len(resume_skills), mj)
        fit, gap = _clamp_display_fit(fit, gap)
        return {
            "resume_skills": resume_skills,
            "market_skill_count": 0,
            "matched_skills": [],
            "missing_skills": [],
            "high_demand_missing_skills": [],
            "fit_percentage": fit,
            "gap_percentage": gap,
            "market_source": "live_corpus",
        }

    async def compute_resume_gap_for_role_from_live_corpus(
        self,
        resume_id: int,
        job_title: str,
        live_jobs: list[dict[str, object]],
    ) -> dict:
        """
        Gap vs target role using only the current scrape batch (titles + extracted skills),
        not the full jobs table aggregate. Falls back to DB aggregate if the batch is empty.
        """
        live_only = get_settings().live_market_only
        logger.info(
            "ROLE USED (gap, live batch): %s batch_jobs=%d",
            (job_title or "").strip(),
            len(live_jobs),
        )
        if not live_jobs:
            if live_only:
                return await self._empty_role_gap_live(resume_id)
            return await self.compute_resume_gap_for_role(resume_id, job_title)

        resume_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_resume_skill_names(resume_id))
        )
        db_jobs = await self.count_jobs_total()
        mj = count_live() if live_only else db_jobs
        filtered = _filter_live_jobs_for_role(live_jobs, job_title)
        demand_rows = _build_live_skill_demand(
            [{"skills": j.get("skills") or j.get("skill_names") or []} for j in filtered]
        )
        if not demand_rows and live_jobs:
            demand_rows = _build_live_skill_demand(
                [{"skills": j.get("skills") or j.get("skill_names") or []} for j in live_jobs]
            )
        if not demand_rows:
            if live_only:
                return await self._empty_role_gap_live(resume_id)
            return await self.compute_resume_gap_for_role(resume_id, job_title)

        market_names = _technical_reference_names([r[0] for r in demand_rows])
        market_set = set(market_names)
        demand_by_name = {
            r[0]: {"id": 0, "name": r[0], "category": None, "count": r[1], "pct": r[2]}
            for r in demand_rows
            if not is_soft_skill(r[0])
        }

        matched, missing = await _matched_missing(
            reference_names=market_names, candidate_names=resume_skills
        )
        candidate_skills = set(resume_skills)
        missing = [s for s in missing if s not in candidate_skills]
        missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]

        # Full-batch list (fallback if live sample yields nothing extractable).
        high_demand_missing_full: list[dict] = []
        for skill_name in missing:
            if skill_name in demand_by_name:
                d = demand_by_name[skill_name]
                high_demand_missing_full.append({
                    "skill_id": d["id"],
                    "skill_name": d["name"],
                    "category": d["category"],
                    "job_count": d["count"],
                    "demand_percentage": d["pct"],
                })
        high_demand_missing_full.sort(key=lambda x: -x["demand_percentage"])

        # "Top skills to learn": first N live jobs only → unique skills, frequency within slice vs resume.
        n_sample = max(1, int(get_settings().top_skills_live_job_sample_size))
        sample_jobs = filtered[:n_sample] if filtered else []
        if not sample_jobs:
            sample_jobs = live_jobs[: min(n_sample, len(live_jobs))]
        demand_rows_sample = _build_live_skill_demand(
            [{"skills": j.get("skills") or j.get("skill_names") or []} for j in sample_jobs]
        )
        high_demand_missing: list[dict] = []
        if demand_rows_sample:
            sample_ref = filter_technical_skills_only(
                normalize_skill_list([r[0] for r in demand_rows_sample])
            )
            _, missing_sample = await _matched_missing(
                reference_names=sample_ref, candidate_names=resume_skills
            )
            missing_sample = [
                s
                for s in missing_sample
                if s not in candidate_skills
                and not is_blocklisted_skill(s)
                and is_plausible_skill_name(s)
            ]
            missing_ok = {s.lower() for s in missing_sample}
            for name, cnt, pct in demand_rows_sample:
                if is_soft_skill(name):
                    continue
                if name.strip().lower() not in missing_ok:
                    continue
                if not is_high_demand_row_acceptable(name):
                    continue
                high_demand_missing.append({
                    "skill_id": 0,
                    "skill_name": name,
                    "category": None,
                    "job_count": cnt,
                    "demand_percentage": pct,
                })
            high_demand_missing.sort(key=lambda x: -x["demand_percentage"])
            high_demand_missing = high_demand_missing[:12]
        # If the N-job slice had no extractable skills, fall back to full-batch top-demand list.
        # If the slice had skills but none are missing vs resume, keep [] (do not inflate from full batch).
        if not high_demand_missing and not demand_rows_sample:
            high_demand_missing = high_demand_missing_full

        raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
        fit, gap = _sanitize_gap_fit(
            round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), mj
        )
        fit, gap = _clamp_display_fit(fit, gap)
        return {
            "resume_skills": resume_skills,
            "market_skill_count": len(market_set),
            "matched_skills": matched,
            "missing_skills": missing,
            "high_demand_missing_skills": high_demand_missing,
            "fit_percentage": fit,
            "gap_percentage": gap,
            "market_source": "live_corpus",
        }

    async def compute_resume_gap_for_role(self, resume_id: int, job_title: str) -> dict:
        if get_settings().live_market_only:
            from app.services.live_job_registry import list_jobs as list_live_jobs

            rows = list_live_jobs(200)
            corpus = [
                {
                    "title": str(r.get("title") or ""),
                    "skills": list(r.get("skill_names") or r.get("skills") or []),
                    "description": str(r.get("description") or "")[:1200],
                }
                for r in rows
            ]
            return await self.compute_resume_gap_for_role_from_live_corpus(
                resume_id, job_title, corpus
            )
        from app.services.job_corpus_service import infer_demand_source
        logger.info("ROLE USED (gap): %s", (job_title or "").strip())

        resume_skills = filter_technical_skills_only(
            normalize_skill_list(await self.get_resume_skill_names(resume_id))
        )
        db_jobs = await self.count_jobs_total()
        demand_list = await skill_demand_percentages_for_title(self.session, job_title)
        # Role slice empty but DB has jobs → use global market (corpus + scraped), never empty market.
        if not demand_list and db_jobs >= 10:
            demand_list_cached = await skill_demand_percentages_cached(self.session)
            if demand_list_cached:
                market_names = _technical_reference_names([d["name"] for d in demand_list_cached])
                market_set = set(market_names)
                matched, missing = await _matched_missing(
                    reference_names=market_names, candidate_names=resume_skills
                )
                candidate_skills = set(resume_skills)
                missing = [s for s in missing if s not in candidate_skills]
                missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
                demand_by_name = {
                    d["name"]: d for d in demand_list_cached if not is_soft_skill(d["name"])
                }
                high_demand_missing: list[dict] = []
                for skill_name in missing:
                    if skill_name in demand_by_name:
                        d = demand_by_name[skill_name]
                        high_demand_missing.append({
                            "skill_id": d["id"],
                            "skill_name": d["name"],
                            "category": d["category"],
                            "job_count": d["count"],
                            "demand_percentage": d["pct"],
                        })
                high_demand_missing.sort(key=lambda x: -x["demand_percentage"])
                raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
                fit, gap = _sanitize_gap_fit(
                    round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), db_jobs
                )
                fit, gap = _clamp_display_fit(fit, gap)
                ms = await infer_demand_source(self.session)
                return {
                    "resume_skills": resume_skills,
                    "market_skill_count": len(market_set),
                    "matched_skills": matched,
                    "missing_skills": missing,
                    "high_demand_missing_skills": high_demand_missing,
                    "fit_percentage": fit,
                    "gap_percentage": gap,
                    "market_source": "corpus" if ms == "corpus" else "scraped",
                }
        if not demand_list:
            market_names = _technical_reference_names(get_synthetic_market_for_role(job_title)[: MAX_JOBS * 2])
            if not market_names:
                fit, gap = _sanitize_gap_fit(100.0, 0.0, len(resume_skills), db_jobs)
                fit, gap = _clamp_display_fit(fit, gap)
                return {
                    "resume_skills": resume_skills,
                    "market_skill_count": 0,
                    "matched_skills": [],
                    "missing_skills": [],
                    "high_demand_missing_skills": [],
                    "fit_percentage": fit,
                    "gap_percentage": gap,
                    "market_source": "synthetic",
                }
            market_set = set(market_names)
            matched, missing = await _matched_missing(
                reference_names=market_names, candidate_names=resume_skills
            )
            candidate_skills = set(resume_skills)
            missing = [s for s in missing if s not in candidate_skills]
            missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
            _synth_pcts = _synthetic_demand_pcts(len(missing))
            high_demand_missing = [
                {"skill_id": 0, "skill_name": s, "category": None, "job_count": 0,
                 "demand_percentage": _synth_pcts[i]}
                for i, s in enumerate(missing)
            ]
            raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
            fit, gap = _sanitize_gap_fit(
                round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), db_jobs
            )
            fit, gap = _clamp_display_fit(fit, gap)
            return {
                "resume_skills": resume_skills,
                "market_skill_count": len(market_set),
                "matched_skills": matched,
                "missing_skills": missing,
                "high_demand_missing_skills": high_demand_missing,
                "fit_percentage": fit,
                "gap_percentage": gap,
                "market_source": "synthetic",
            }
        # skill_demand_percentages_for_title returns ORM tuples (not cached)
        market_names = _technical_reference_names([s.name for s, _c, _p in demand_list])
        market_set = set(market_names)
        matched, missing = await _matched_missing(
            reference_names=market_names, candidate_names=resume_skills
        )
        candidate_skills = set(resume_skills)
        missing = [s for s in missing if s not in candidate_skills]
        missing = [s for s in missing if not is_blocklisted_skill(s) and is_plausible_skill_name(s)]
        # This function uses the uncached ORM version, so unpack tuples here
        demand_by_name_orm = {
            s.name: (s, cnt, pct)
            for s, cnt, pct in demand_list
            if not is_soft_skill(s.name)
        }
        high_demand_missing = []
        for skill_name in missing:
            if skill_name in demand_by_name_orm:
                skill, cnt, pct = demand_by_name_orm[skill_name]
                high_demand_missing.append({
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "category": skill.category,
                    "job_count": cnt,
                    "demand_percentage": pct,
                })
        high_demand_missing.sort(key=lambda x: -x["demand_percentage"])
        raw_fit = (len(matched) / len(market_set) * 100.0) if market_set else 100.0
        fit, gap = _sanitize_gap_fit(
            round(raw_fit, 2), round(100.0 - raw_fit, 2), len(resume_skills), db_jobs
        )
        fit, gap = _clamp_display_fit(fit, gap)
        return {
            "resume_skills": resume_skills,
            "market_skill_count": len(market_set),
            "matched_skills": matched,
            "missing_skills": missing,
            "high_demand_missing_skills": high_demand_missing,
            "fit_percentage": fit,
            "gap_percentage": gap,
            "market_source": "scraped",
        }

    async def project_fit_with_skills(
        self,
        resume_id: int,
        skills_to_add: list[str],
        target_role: str | None,
    ) -> dict:
        """Simulate market fit after adding hypothetical skills (no DB write)."""
        from app.services.normalization import normalize_role

        role = normalize_role(target_role or "")
        role = (role or "").strip()
        if not role:
            raise ValueError("Target role is required for projection")
        logger.info("ROLE USED (scoring): %s", role)
        base = await self.compute_resume_gap_for_role(resume_id, role)
        prev_fit = float(base["fit_percentage"])
        extra = filter_technical_skills_only(
            normalize_skill_list([x for x in skills_to_add if x and str(x).strip()])
        )
        if not extra:
            return {
                "previous_fit": prev_fit,
                "new_fit": prev_fit,
                "improvement": 0.0,
                "skills_added": [],
                "market_skill_count": base.get("market_skill_count", 0),
            }
        hyp = normalize_skill_list(list(base["resume_skills"]) + extra)
        db_jobs = await self.count_jobs_total()
        live_only = get_settings().live_market_only
        market_names: list[str]
        if live_only:
            market_names = market_names_for_role_live(role)
        else:
            demand_orm = await skill_demand_percentages_for_title(self.session, role)
            if demand_orm:
                market_names = _technical_reference_names([s.name for s, _c, _p in demand_orm])
            elif db_jobs >= 10:
                dl = await skill_demand_percentages_cached(self.session)
                market_names = _technical_reference_names([d["name"] for d in dl]) if dl else []
            else:
                market_names = _technical_reference_names(
                    list(get_synthetic_market_for_role(role) or [])[: MAX_JOBS * 2]
                )
        if not market_names:
            return {
                "previous_fit": prev_fit,
                "new_fit": prev_fit,
                "improvement": 0.0,
                "skills_added": extra,
                "market_skill_count": 0,
            }
        market_set = set(market_names)
        matched_new, _ = await _matched_missing(
            reference_names=market_names, candidate_names=hyp,
        )
        raw_fit = (len(matched_new) / len(market_set) * 100.0) if market_set else prev_fit
        mj = count_live() if live_only else db_jobs
        fit, gap = _sanitize_gap_fit(
            round(raw_fit, 2), round(100.0 - raw_fit, 2), len(hyp), mj
        )
        fit, _ = _clamp_display_fit(fit, gap)
        improvement = round(fit - prev_fit, 2)
        return {
            "previous_fit": prev_fit,
            "new_fit": fit,
            "improvement": improvement,
            "skills_added": extra,
            "market_skill_count": len(market_set),
        }

    async def project_fit_multistep(
        self,
        resume_id: int,
        skills_to_add: list[str],
        target_role: str | None,
        *,
        n_steps: int = 3,
    ) -> dict:
        """Cumulative fit after adding skills in chunks; includes rough week estimates per step."""
        from app.services.normalization import normalize_role

        role = normalize_role(target_role or "")
        role = (role or "").strip()
        if not role:
            raise ValueError("Target role is required for projection")
        logger.info("ROLE USED (scoring): %s", role)
        base = await self.compute_resume_gap_for_role(resume_id, role)
        prev_fit = float(base["fit_percentage"])
        extra = filter_technical_skills_only(
            normalize_skill_list([x for x in skills_to_add if x and str(x).strip()])
        )
        if not extra:
            return {
                "previous_fit": prev_fit,
                "new_fit": prev_fit,
                "improvement": 0.0,
                "skills_added": [],
                "market_skill_count": base.get("market_skill_count", 0),
                "steps": [],
            }
        db_jobs = await self.count_jobs_total()
        live_only = get_settings().live_market_only
        if live_only:
            market_names = market_names_for_role_live(role)
        else:
            demand_orm = await skill_demand_percentages_for_title(self.session, role)
            if demand_orm:
                market_names = _technical_reference_names([s.name for s, _c, _p in demand_orm])
            elif db_jobs >= 10:
                dl = await skill_demand_percentages_cached(self.session)
                market_names = _technical_reference_names([d["name"] for d in dl]) if dl else []
            else:
                market_names = _technical_reference_names(
                    list(get_synthetic_market_for_role(role) or [])[: MAX_JOBS * 2]
                )
        if not market_names:
            return {
                "previous_fit": prev_fit,
                "new_fit": prev_fit,
                "improvement": 0.0,
                "skills_added": extra,
                "market_skill_count": 0,
                "steps": [],
            }
        market_set = set(market_names)
        n_steps = max(1, min(5, int(n_steps)))
        chunk_sz = max(1, (len(extra) + n_steps - 1) // n_steps)
        steps_out: list[dict] = []
        acc = list(base["resume_skills"])
        last_fit = prev_fit
        for i in range(n_steps):
            part = extra[i * chunk_sz : (i + 1) * chunk_sz]
            if not part:
                break
            acc = normalize_skill_list(acc + part)
            matched_new, _ = await _matched_missing(
                reference_names=market_names, candidate_names=acc,
            )
            raw_fit = (len(matched_new) / len(market_set) * 100.0) if market_set else last_fit
            mj = count_live() if live_only else db_jobs
            fit, gap = _sanitize_gap_fit(
                round(raw_fit, 2), round(100.0 - raw_fit, 2), len(acc), mj
            )
            fit, _ = _clamp_display_fit(fit, gap)
            weeks = 2 + i * 4
            steps_out.append({
                "step": i + 1,
                "skills": part,
                "fit": fit,
                "weeks_estimate": weeks,
            })
            last_fit = fit
        improvement = round(last_fit - prev_fit, 2)
        return {
            "previous_fit": prev_fit,
            "new_fit": last_fit,
            "improvement": improvement,
            "skills_added": extra,
            "market_skill_count": len(market_set),
            "steps": steps_out,
        }
