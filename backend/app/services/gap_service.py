"""
GapAnalysisService — orchestrates the full resume gap analysis flow.

Extracted from analysis.py router so the router becomes a thin HTTP adapter.
Flow: ensure skills → build search terms → freshness check → scrape (progressive)
      → background remainder → compute gap → data quality → LLM advice → categorize.
"""
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, Resume
from app.schemas.match import (
    BestNextActionOut,
    CareerInsightsOut,
    DataQualityMeta,
    GapAdviceStructuredOut,
    ResumeGapOut,
    SkillDemandOut,
)
from app.services.llm_service import (
    gap_advice as llm_gap_advice,
    is_llm_enabled,
    verify_high_demand_missing_skills_llm,
)
from app.services.live_job_registry import count_live, list_jobs_as_gap_corpus
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id
from app.services.match_service import MatchService, _synthetic_demand_pcts
from app.services.skill_normalizer import expand_resume_skill_coverage
from app.services.normalization import (
    expand_role_family,
    experience_interpretation,
    normalize_role,
    parse_experience,
    role_scrape_tokens,
)
from app.services.resume_service import (
    ResumeService,
    extract_experience_years,
    suggest_roles_from_resume,
)
from app.services.scrape_cache import (
    compute_data_quality,
    get_last_scrape_time,
    is_fresh,
    make_scrape_key,
    record_scrape_time,
    release_scrape_lock,
    try_acquire_scrape_lock,
)
from app.services.job_corpus_service import ensure_minimum_market_jobs
from app.services.scraper_service import ScraperService, ensure_synthetic_fallback_jobs
from app.services.career_stats_service import record_missing_skill_stats
from app.services.career_progress_service import record_career_progress_snapshot
from app.services.confidence_service import gap_confidence
from app.services.decision_engine_service import build_predictive_gap_bundle
from app.services.trajectory_service import predict_career_trajectory
from app.services.role_fit_service import suggest_roles_from_corpus
from app.services.skill_service import (
    filter_high_demand_rows_heuristic,
    get_skills_for_scrape,
    invalidate_skill_demand_caches,
    is_high_demand_row_acceptable,
    skill_growth_by_name,
)
from app.schemas.match import MATCHING_EXPLANATION

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Skill category map built from skills_dictionary.json categories.
# Used to group missing skills into weakness buckets for the UI.
# ---------------------------------------------------------------------------
_CATEGORY_DISPLAY: dict[str, str] = {
    "programming": "Programming",
    "ml_frameworks": "ML Frameworks",
    "nlp": "NLP",
    "computer_vision": "Computer Vision",
    "ml_ops": "MLOps / DevOps",
    "cloud": "Cloud",
    "data_engineering": "Data Engineering",
    "statistics": "Statistics & Math",
    "tools": "Tools",
}

# Flat reverse lookup: lowercase skill name → display category name
_SKILL_TO_CATEGORY: dict[str, str] = {}


def _build_category_map() -> None:
    """Lazy-build skill→category reverse map from skills_dictionary.json."""
    if _SKILL_TO_CATEGORY:
        return
    from pathlib import Path
    import json
    path = Path(__file__).resolve().parents[2] / "data" / "skills_dictionary.json"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        data: dict[str, list[str]] = json.load(f)
    for raw_cat, skills in data.items():
        display = _CATEGORY_DISPLAY.get(raw_cat, raw_cat.replace("_", " ").title())
        for skill in skills:
            if skill and isinstance(skill, str):
                _SKILL_TO_CATEGORY[skill.lower()] = display


def domain_match_counts(matched_skills: list[str]) -> dict[str, int]:
    """Count how many matched skills fall in each dictionary category (for insights)."""
    _build_category_map()
    counts: dict[str, int] = {}
    for s in matched_skills:
        cat = _SKILL_TO_CATEGORY.get(s.lower(), "Other")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _insights_strongest_domain(matched_skills: list[str]) -> str:
    if not matched_skills:
        return "Add core technical skills to establish a clear domain."
    counts = domain_match_counts(list(matched_skills))
    if not counts:
        return "Generalist profile — deepen one stack to stand out."
    best = max(counts.items(), key=lambda x: x[1])
    return f"{best[0]} ({best[1]} matched skills)"


def build_career_insights_dict(
    *,
    gap: dict,
    role_fits: list[dict],
    roi_skill: str | None,
    roi_score: float | None,
    median_market_fit: float = 52.0,
    projected_fit_delta: float | None = None,
    target_role_label: str | None = None,
) -> dict:
    """Deterministic advisor copy; shape matches CareerInsightsOut."""
    lines: list[str] = []
    headline_closest = ""
    if len(role_fits) >= 1:
        top = role_fits[0]
        r0, f0 = top.get("role", ""), float(top.get("fit") or 0)
        if len(role_fits) >= 2:
            f1 = float(role_fits[1].get("fit") or 0)
            delta = round(f0 - f1, 1)
            headline_closest = (
                f"You are closest to “{r0}” ({f0:.0f}% corpus fit vs next role Δ {delta:+.1f} pts)."
            )
            lines.append(headline_closest)
        else:
            headline_closest = f"Top corpus-aligned role: “{r0}” ({f0:.0f}% fit)."
            lines.append(headline_closest)

    headline_roi = ""
    if roi_skill:
        extra = f" (demand × growth priority {roi_score:.1f})" if roi_score is not None else ""
        headline_roi = f"Learning {roi_skill} has the highest ROI in your current market slice{extra}."
        lines.append(headline_roi)

    dom = _insights_strongest_domain(list(gap.get("matched_skills") or []))
    headline_domain = f"Your strongest domain signal: {dom}."
    lines.append(headline_domain)

    fit = float(gap.get("fit_percentage") or 0)
    slice_label = target_role_label or (role_fits[0].get("role") if role_fits else "this market slice")
    ahead = int(min(93, max(6, round(48 + (fit - median_market_fit) * 1.25))))
    headline_ahead = (
        f"In {slice_label}, you appear ahead of about {ahead}% of candidates vs our median benchmark "
        f"(~{median_market_fit:.0f}% fit)."
    )
    lines.append(headline_ahead)
    vs_median = (
        f"Your estimated market fit is {fit - median_market_fit:+.1f} points vs that median benchmark "
        f"({fit:.0f}% vs ~{median_market_fit:.0f}%)."
    )
    lines.append(vs_median)

    headline_roi_pct = ""
    if projected_fit_delta is not None and projected_fit_delta >= 1.0:
        headline_roi_pct = (
            f"Closing highlighted skill gaps could lift estimated market fit by about +{projected_fit_delta:.0f}%."
        )
        lines.append(headline_roi_pct)

    return {
        "headline_closest_role": headline_closest,
        "headline_roi_skill": headline_roi,
        "headline_strongest_domain": headline_domain,
        "headline_ahead_of_peers": headline_ahead,
        "comparison_vs_median": vs_median,
        "headline_roi_percent": headline_roi_pct,
        "detail_lines": lines[:10],
    }


def categorize_missing_skills(missing_skills: list[str]) -> dict[str, list[str]]:
    """
    Group missing skills by category.
    Returns e.g. {"Cloud": ["AWS", "GCP"], "MLOps / DevOps": ["Docker", "Kubernetes"]}.
    Skills not in the dictionary go into "Other".
    """
    _build_category_map()
    result: dict[str, list[str]] = {}
    for skill in missing_skills:
        cat = _SKILL_TO_CATEGORY.get(skill.lower(), "Other")
        result.setdefault(cat, []).append(skill)
    return result


def generate_learning_path(missing_skills: list[str], experience_level: str | None = None) -> list[str]:
    """
    Generate an ordered, actionable learning path for missing skills.
    Sequencing: foundational skills first (programming, statistics), then
    ML frameworks, then domain-specific (NLP/CV), then infrastructure (cloud, mlops), then tools.
    """
    _build_category_map()
    priority_order = [
        "Programming",
        "Statistics & Math",
        "ML Frameworks",
        "NLP",
        "Computer Vision",
        "Data Engineering",
        "Cloud",
        "MLOps / DevOps",
        "Tools",
        "Other",
    ]
    if experience_level == "senior":
        priority_order = [
            "ML Frameworks",
            "Cloud",
            "MLOps / DevOps",
            "Data Engineering",
            "NLP",
            "Computer Vision",
            "Programming",
            "Statistics & Math",
            "Tools",
            "Other",
        ]
    by_category: dict[str, list[str]] = {}
    for skill in missing_skills:
        cat = _SKILL_TO_CATEGORY.get(skill.lower(), "Other")
        by_category.setdefault(cat, []).append(skill)

    steps: list[str] = []
    for cat in priority_order:
        skills = by_category.get(cat, [])
        if not skills:
            continue
        if len(skills) == 1:
            steps.append(f"Learn {skills[0]} ({cat})")
        elif len(skills) <= 3:
            joined = ", ".join(skills[:-1]) + f" and {skills[-1]}"
            steps.append(f"Learn {joined} ({cat})")
        else:
            sample = ", ".join(skills[:3])
            steps.append(f"Build {cat} foundation: start with {sample} (+{len(skills) - 3} more)")
    if experience_level == "entry":
        steps.insert(0, "Prioritize programming and statistics fundamentals before depth specialization")
    elif experience_level == "senior":
        steps.append("Advanced scope: architecture tradeoffs, reliability at scale, and mentoring")
    return steps


def _prioritize_user_target_in_suggested(
    suggested: list[str],
    normalized_role: str,
    user_specified_target: bool,
) -> list[str]:
    """When the user typed a target role, show that chip first (deduped)."""
    if not user_specified_target or not (normalized_role or "").strip():
        return list(suggested)
    nr = normalized_role.strip().lower()
    display = normalized_role.strip().title()
    rest = [s for s in suggested if (s or "").strip().lower() != nr]
    return [display] + rest


def _describe_weaknesses(by_category: dict[str, list[str]]) -> list[str]:
    """
    Convert category buckets into human-readable weakness strings.
    e.g. "You are weak in Cloud skills (AWS, GCP missing)"
    Only surfaces categories with ≥ 2 missing skills or 1 high-priority one.
    """
    summaries: list[str] = []
    for cat, skills in sorted(by_category.items(), key=lambda x: -len(x[1])):
        if cat == "Other":
            continue
        sample = ", ".join(skills[:3])
        suffix = f" and {len(skills) - 3} more" if len(skills) > 3 else ""
        summaries.append(f"You are weak in {cat} skills ({sample}{suffix} missing)")
    return summaries


class GapAnalysisService:
    def __init__(self, session: AsyncSession, arq_pool=None):
        self.session = session
        # arq_pool: optional ArqRedis pool used to enqueue background_scrape_task.
        # When None (Redis unavailable or sync fallback path) progressive scraping
        # is still used but the background remainder is dropped silently.
        self.arq_pool = arq_pool

    async def analyze(
        self,
        resume_id: int,
        target_role: str | None = None,
        experience_input: str | None = None,
        *,
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ResumeGapOut:
        t0 = time.perf_counter()

        async def _notify(percent: int | None, message: str) -> None:
            if on_progress is not None:
                payload: dict[str, Any] = {"message": message}
                if percent is not None:
                    payload["percent"] = percent
                await on_progress(payload)

        async def _emit(step: int, message: str) -> None:
            pct = (25, 50, 75, 92)[step - 1]
            await _notify(pct, message)

        async def _log(message: str) -> None:
            await _notify(None, message)

        # 1. Validate resume
        resume = await self.session.get(Resume, resume_id)
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
        await _log("Resume loaded")

        # 2. Ensure skills are extracted
        resume_svc = ResumeService(self.session)
        await resume_svc.ensure_resume_skills(resume_id)
        await self.session.flush()

        suggested = suggest_roles_from_resume(resume.raw_text or "")

        raw_role = (target_role or "").strip()
        user_specified_target_role = bool(raw_role)
        if len(raw_role) > 100:
            raw_role = raw_role[:100].strip()
        raw_exp = (experience_input or "").strip()
        if len(raw_exp) > 100:
            raw_exp = raw_exp[:100].strip()

        if not raw_role and suggested:
            raw_role = suggested[0]

        logger.info("ROLE SUGGESTIONS (final): %s", suggested)

        normalized_role = normalize_role(raw_role) if raw_role else ""
        normalized_role = (normalized_role or "").strip()
        if not normalized_role:
            raise ValueError("Please enter a target role")

        logger.info("ROLE SOURCE: %s", "user" if target_role else "resume")
        logger.info("ROLE USED (raw): %s", raw_role)
        logger.info("ROLE USED (normalized): %s", normalized_role)

        exp_parsed = parse_experience(raw_exp)
        exp_level = exp_parsed.get("level") or "unknown"
        user_years = exp_parsed.get("years")
        exp_years = user_years
        exp_display = experience_interpretation(exp_parsed)

        # Reconcile experience from resume text vs user input — prefer the higher value.
        resume_years = extract_experience_years(resume.raw_text or "")
        user_years_num = float(user_years) if isinstance(user_years, (int, float)) and user_years is not None else 0.0
        final_years = max(float(resume_years), user_years_num)
        # Final safety clamp for unrealistic / malformed values.
        final_years = min(max(final_years, 0.0), 40.0)
        # Log only when there is a meaningful disagreement (>1 year); never fail the request.
        if resume_years and user_years_num and abs(float(resume_years) - user_years_num) > 1.0:
            logger.warning(
                "gap_analysis resume_id=%d: experience mismatch resume_text=%.1f user_input=%.1f using=%.1f",
                resume_id,
                float(resume_years),
                user_years_num,
                final_years,
            )

        # Derive coarse level from reconciled years to keep scoring and advice consistent.
        if final_years > 0.0:
            fy_int = int(final_years)
            if fy_int <= 1:
                lvl = "entry"
            elif fy_int <= 3:
                lvl = "junior"
            elif fy_int <= 6:
                lvl = "mid"
            else:
                lvl = "senior"
            exp_level = lvl
            exp_years = fy_int
            exp_display = experience_interpretation({"level": lvl, "years": fy_int})

        role_extra = role_scrape_tokens(normalized_role)
        for role_v in expand_role_family(normalized_role):
            if role_v and role_v not in role_extra:
                role_extra.append(role_v)

        # 3. Build search terms — role + resume only (no global DB "top demand" terms).
        # Including market_top_n from the DB skews LinkedIn SERPs toward whatever is hot globally
        # (often ML/DS), so scraped jobs and extracted "skills" no longer match the user's target role.
        logger.info("ROLE USED (scraper): %s", normalized_role)
        skill_terms = await get_skills_for_scrape(
            self.session,
            resume_id=resume_id,
            market_top_n=0,
            extra_skill_names=role_extra,
        )
        if not skill_terms:
            raise ValueError("No skills could be extracted from the resume. Ensure the PDF has readable text.")

        await _log("Search keywords ready for market fetch")
        await _emit(1, "Resume validated; skills extracted; search terms ready")

        settings = get_settings()
        location = settings.scraper_default_location
        max_age_hours = settings.scrape_freshness_hours

        # 4. Freshness check + distributed scrape lock
        cache_key = make_scrape_key(skill_terms, location, normalized_role)
        last_scrape = await get_last_scrape_time(cache_key)
        scrape_result: dict = {
            "portals": {},
            "total_new": 0,
            "total_cached": 0,
            "errors": [],
            "links_parsed_total": 0,
            "scraped_quick_jobs": 0,
            "market_scrape_degraded": False,
            "db_jobs_count": 0,
            "scrape_health": {"links_found": 0, "is_degraded": False, "reason": "success"},
            "live_job_corpus": [],
        }
        data_source: str  # DataQualityMeta.source label

        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_job_count = int(
            (
                await self.session.execute(
                    select(func.count(Job.id)).where(Job.created_at >= cutoff_24h)
                )
            ).scalar()
            or 0
        )
        live_in_memory = count_live()
        live_only = bool(getattr(settings, "live_market_only", False))
        has_market_for_skip = (
            live_in_memory > 0 if live_only else recent_job_count > 0
        )

        if settings.demo_mode:
            # Demo mode is deterministic: skip live scraping and rely on corpus/synthetic fallback chain.
            logger.info("gap_analysis demo_mode enabled — skipping live scrape")
            await _log("Demo mode: skipping live scrape")
            data_source = "demo_mode"
        elif is_fresh(last_scrape, max_age_hours=max_age_hours) and has_market_for_skip:
            # Data is within the freshness window and we have recent job rows — skip scraping.
            logger.info(
                "gap_analysis resume_id=%d: fresh data (%.1fh old) — skipping scrape",
                resume_id,
                (datetime.now(timezone.utc) - last_scrape).total_seconds() / 3600.0
                if last_scrape
                else 0.0,
            )
            await _log("Market cache is fresh; skipping live scrape")
            data_source = "fresh_cache"
        else:
            no_recent_jobs = recent_job_count == 0 and not live_only
            no_live_registry = live_only and live_in_memory == 0
            force_refresh_scrape = (
                is_fresh(last_scrape, max_age_hours=max_age_hours)
                and (no_recent_jobs or no_live_registry)
            )
            if force_refresh_scrape:
                logger.info("scrape override: forcing scrape due to no recent jobs")
            lock_acquired = await try_acquire_scrape_lock(cache_key)
            if not lock_acquired:
                # Another worker is already scraping for this (skill_terms, location).
                # Use whatever is in the DB right now rather than waiting.
                logger.info(
                    "gap_analysis resume_id=%d: scrape lock busy — skipping scrape",
                    resume_id,
                )
                await _log(
                    "Another scrape in progress; using in-memory live jobs"
                    if live_only
                    else "Another scrape in progress; using jobs already in the database"
                )
                data_source = "concurrent_lock"
            else:
                # We hold the lock — run the quick (synchronous) batch now and hand
                # the remainder to a background ARQ task.
                try:
                    await _log("Running quick LinkedIn job scrape (India, last 24h)…")
                    scraper_svc = ScraperService(self.session)
                    scrape_result, remaining_urls = await scraper_svc.scrape_quick(
                        skill_terms,
                        portal_ids=None,
                        max_quick=5,
                        posted_within_hours=settings.scraper_default_time_window_hours,
                        location=location,
                        force_refresh=force_refresh_scrape,
                    )
                    await self.session.commit()

                    # Enqueue background task for remaining URLs if ARQ is available.
                    if remaining_urls and self.arq_pool is not None:
                        try:
                            await self.arq_pool.enqueue_job(
                                "background_scrape_task",
                                skill_terms,
                                remaining_urls,
                                location,
                                cache_key,
                                _job_id=f"bg_scrape:{cache_key}",
                            )
                            logger.info(
                                "gap_analysis resume_id=%d: enqueued background_scrape_task "
                                "for %d remaining URLs",
                                resume_id,
                                len(remaining_urls),
                            )
                        except Exception as enq_exc:
                            # Non-fatal: background scraping is best-effort.
                            logger.warning(
                                "gap_analysis: failed to enqueue background_scrape_task: %s",
                                enq_exc,
                            )

                    await record_scrape_time(cache_key)
                    sh = scrape_result.get("scrape_health") or {}
                    await _log(
                        f"Scrape finished — {int(sh.get('links_found') or 0)} listing links parsed"
                        + (" (degraded)" if sh.get("is_degraded") else "")
                    )
                    data_source = "live_scrape"
                finally:
                    # Always release the lock so the next request doesn't wait for TTL.
                    await release_scrape_lock(cache_key)

        # Curated corpus + synthetic rows — only when DB-backed market aggregates are allowed.
        corp_added = 0
        corp_action = "skipped_live_market_only"
        if not live_only:
            corp_added, corp_action = await ensure_minimum_market_jobs(
                self.session,
                min_jobs=settings.job_corpus_min_for_gap,
            )
            if corp_added:
                await self.session.commit()
                await invalidate_skill_demand_caches()
                logger.info(
                    "gap_analysis resume_id=%d: corpus_backfill inserted=%d action=%s",
                    resume_id,
                    corp_added,
                    corp_action,
                )

        logger.info(
            "gap_analysis resume_id=%d keywords=%s data_source=%s scrape_health=%s corpus_action=%s",
            resume_id,
            skill_terms[:15],
            data_source,
            scrape_result.get("scrape_health"),
            corp_action,
        )

        synthetic_inserted = 0
        if not live_only:
            synthetic_inserted = await ensure_synthetic_fallback_jobs(self.session)
            if synthetic_inserted > 0:
                logger.warning(
                    "gap_analysis resume_id=%d: inserted %d synthetic fallback job(s)",
                    resume_id,
                    synthetic_inserted,
                )
                await self.session.commit()
                await invalidate_skill_demand_caches()

        await _emit(2, "Market jobs pipeline ready (scrape, cache, corpus)")

        await _log("Scoring resume fit vs target role and demand…")
        # 5. Compute gap metrics (role-focused market slice)
        match_svc = MatchService(self.session)
        live_corpus = list(scrape_result.get("live_job_corpus") or [])
        if live_only and not live_corpus:
            live_corpus = list_jobs_as_gap_corpus(200)
        use_live_corpus = (
            isinstance(live_corpus, list)
            and len(live_corpus) > 0
            and (
                live_only
                or (data_source == "live_scrape")
            )
        )
        if use_live_corpus:
            logger.info(
                "gap_analysis resume_id=%d: scoring vs live job corpus (%d row(s)), not DB-wide demand",
                resume_id,
                len(live_corpus),
            )
            gap = await match_svc.compute_resume_gap_for_role_from_live_corpus(
                resume_id, normalized_role, live_corpus
            )
        else:
            gap = await match_svc.compute_resume_gap_for_role(resume_id, normalized_role)
        if synthetic_inserted > 0:
            gap["market_source"] = "synthetic"

        # Defensive guard: never report skills the resume already covers (exact + word atoms).
        resume_skill_set = expand_resume_skill_coverage([str(s) for s in (gap.get("resume_skills") or []) if s])
        gap["missing_skills"] = [
            s for s in (gap.get("missing_skills") or [])
            if str(s).strip().lower() not in resume_skill_set
        ]
        # Keep high-demand list aligned with missing_skills (was stale when missing was pruned above).
        miss_set = {str(s).strip().lower() for s in gap["missing_skills"]}
        gap["high_demand_missing_skills"] = [
            x
            for x in (gap.get("high_demand_missing_skills") or [])
            if str(x.get("skill_name") or "").strip().lower() in miss_set
        ]

        growth_map: dict[str, float] = (
            {} if live_only else await skill_growth_by_name(self.session)
        )
        hd_list = gap.get("high_demand_missing_skills") or []
        verified_hd: list[dict] | None = None
        if hd_list:

            def _prio_row(x: dict) -> float:
                sn = (x.get("skill_name") or "").lower()
                g = max(0.0, float(growth_map.get(sn, 0.0)))
                d = float(x.get("demand_percentage") or 0.0)
                return -(d * (1.0 + g / 100.0))

            hd_list.sort(key=_prio_row)
            gap["high_demand_missing_skills"] = hd_list
            verified_hd = (
                await verify_high_demand_missing_skills_llm(hd_list[:45], normalized_role or "")
                if is_llm_enabled()
                else None
            )
            if verified_hd is not None:
                gap["high_demand_missing_skills"] = verified_hd
                logger.info(
                    "gap_analysis resume_id=%d: top_skills_llm_verified=%d (candidates=%d)",
                    resume_id,
                    len(verified_hd),
                    len(hd_list),
                )
            else:
                gap["high_demand_missing_skills"] = filter_high_demand_rows_heuristic(hd_list)
                logger.info(
                    "gap_analysis resume_id=%d: top_skills_heuristic=%d (candidates=%d, llm_off_or_failed)",
                    resume_id,
                    len(gap["high_demand_missing_skills"]),
                    len(hd_list),
                )

        # If the local LLM rejected every candidate, do not replace with unverified missing_skills.
        skip_missing_skills_fallback = bool(hd_list) and verified_hd is not None and len(verified_hd) == 0

        # If market-demand slice is empty, backfill from missing_skills (Ollama-verified when enabled).
        if (
            not gap.get("high_demand_missing_skills")
            and gap.get("missing_skills")
            and not skip_missing_skills_fallback
        ):
            seen_ms: set[str] = set()
            ms_out: list[str] = []
            for s in gap["missing_skills"]:
                if not s:
                    continue
                t = str(s).strip()
                if not t:
                    continue
                k = t.lower()
                if k in seen_ms:
                    continue
                if not is_high_demand_row_acceptable(t):
                    continue
                seen_ms.add(k)
                ms_out.append(t)
                if len(ms_out) >= 12:
                    break
            if ms_out:
                _synth_pcts = _synthetic_demand_pcts(len(ms_out))
                synth_rows = [
                    {
                        "skill_id": 0,
                        "skill_name": name,
                        "category": None,
                        "job_count": 0,
                        "demand_percentage": _synth_pcts[i],
                    }
                    for i, name in enumerate(ms_out)
                ]
                if is_llm_enabled():
                    v2 = await verify_high_demand_missing_skills_llm(
                        synth_rows[:45], normalized_role or ""
                    )
                    if v2 is not None:
                        gap["high_demand_missing_skills"] = v2
                        logger.info(
                            "gap_analysis resume_id=%d: top_skills_from_missing_llm_verified=%d",
                            resume_id,
                            len(v2),
                        )
                    else:
                        gap["high_demand_missing_skills"] = filter_high_demand_rows_heuristic(synth_rows)
                        logger.info(
                            "gap_analysis resume_id=%d: top_skills_from_missing_heuristic=%d (llm_failed)",
                            resume_id,
                            len(gap["high_demand_missing_skills"]),
                        )
                else:
                    gap["high_demand_missing_skills"] = filter_high_demand_rows_heuristic(synth_rows)
                    logger.info(
                        "gap_analysis resume_id=%d: top_skills_from_missing_heuristic=%d (llm_off)",
                        resume_id,
                        len(gap["high_demand_missing_skills"]),
                    )

        projected_fit = float(gap["fit_percentage"])
        mcount = gap.get("market_skill_count") or 0
        top_miss = gap.get("high_demand_missing_skills") or []
        if mcount > 0 and top_miss:
            per_skill = min(100.0 / mcount, 25.0)
            gain = min(100.0 - projected_fit, per_skill * min(5, len(top_miss)))
            projected_fit = round(min(100.0, projected_fit + gain), 1)

        await record_missing_skill_stats(gap.get("missing_skills") or [])
        await _emit(3, "Fit vs target role scored; demand weighting applied")
        role_rows = await suggest_roles_from_corpus(self.session, resume_id)
        roi_skill = None
        roi_score_val = None
        hd_final = gap.get("high_demand_missing_skills") or []
        if hd_final:
            top = hd_final[0]
            roi_skill = top.get("skill_name")
            sn = (roi_skill or "").lower()
            g = max(0.0, float(growth_map.get(sn, 0.0)))
            roi_score_val = float(top.get("demand_percentage") or 0.0) * (1.0 + g / 100.0)
        projected_delta = round(float(projected_fit) - float(gap["fit_percentage"]), 1)
        insights_raw = build_career_insights_dict(
            gap=gap,
            role_fits=role_rows,
            roi_skill=roi_skill,
            roi_score=roi_score_val,
            median_market_fit=52.0,
            projected_fit_delta=projected_delta,
            target_role_label=normalized_role,
        )

        sh = scrape_result.get("scrape_health") or {}
        # 6. Data quality metadata
        data_quality = await compute_data_quality(
            self.session,
            last_scrape=last_scrape,
            max_age_hours=max_age_hours,
            source=data_source,
            synthetic_fallback_used=synthetic_inserted > 0,
            scrape_degraded=bool(scrape_result.get("market_scrape_degraded")),
            scrape_health_reason=sh.get("reason"),
            live_jobs_count=count_live() if live_only else None,
        )

        job_fetch_notice: str | None = None
        if data_quality.quality_band == "low":
            job_fetch_notice = "⚠ Limited live data — results are estimated."
        elif getattr(data_quality, "demand_source", None) == "corpus" and data_source != "live_scrape":
            job_fetch_notice = "Showing curated market examples (offline corpus)."
        elif data_source == "live_scrape" and scrape_result.get("market_scrape_degraded"):
            if data_quality.jobs_count > 0:
                job_fetch_notice = "Unable to fetch fresh jobs — showing cached results"
            else:
                job_fetch_notice = "Try again or change role"

        if synthetic_inserted > 0:
            fb = "Using fallback sample job rows so skills and fit stay available."
            if not job_fetch_notice:
                job_fetch_notice = fb
            elif fb.lower() not in (job_fetch_notice or "").lower():
                job_fetch_notice = f"{job_fetch_notice} {fb}"

        gap_conf = gap_confidence(
            jobs_count=data_quality.jobs_count,
            market_skill_count=gap.get("market_skill_count") or 0,
            quality_band=data_quality.quality_band,
        )

        await _emit(4, "Building advice, learning path & recommendations")

        # 7. Optional LLM advice
        if is_llm_enabled():
            await _log("LLM: generating structured gap advice…")
        ai_advice: str | None = None
        ai_advice_structured: GapAdviceStructuredOut | None = None
        if is_llm_enabled():
            live_llm = scrape_result.get("live_job_corpus") or []
            use_live_llm = isinstance(live_llm, list) and any(
                isinstance(x, dict) and (str(x.get("description") or "").strip())
                for x in live_llm
            )
            market_parts: list[str] = []
            if use_live_llm:
                for entry in live_llm[:12]:
                    if not isinstance(entry, dict):
                        continue
                    title = (entry.get("title") or "Job").strip()
                    desc = (str(entry.get("description") or "").strip())[:500]
                    market_parts.append(f"Title: {title}\n{desc}")
                market_job_descriptions = "\n\n---\n\n".join(market_parts) if market_parts else ""
            else:
                job_rows = (
                    await self.session.execute(
                        select(Job).order_by(Job.id.desc()).limit(24)
                    )
                ).scalars().all()
                target_n = 8
                linkedin_jobs = [j for j in job_rows if "linkedin" in (j.source or "").lower()]
                other_jobs = [j for j in job_rows if "linkedin" not in (j.source or "").lower()]
                min_li = int(0.3 * target_n)
                if len(linkedin_jobs) >= min_li:
                    job_rows = (linkedin_jobs[:min_li] + other_jobs[: max(0, target_n - min_li)])[:target_n]
                else:
                    job_rows = job_rows[:target_n]
                for j in job_rows:
                    title = (j.title or "Job").strip()
                    company = (j.company or "").strip()
                    desc = ((j.description or "").strip())[:500]
                    market_parts.append(
                        f"Title: {title}" + (f" | Company: {company}" if company else "") + f"\n{desc}"
                    )
                market_job_descriptions = "\n\n---\n\n".join(market_parts) if market_parts else ""
            resume_excerpt = " ".join((resume.raw_text or "").strip().split())[:3000]
            structured, fallback = await llm_gap_advice(
                your_skills=gap["resume_skills"],
                matched_skills=gap["matched_skills"],
                missing_skills=gap["missing_skills"],
                high_demand_missing=gap["high_demand_missing_skills"],
                market_job_descriptions=market_job_descriptions,
                resume_text=resume_excerpt,
                target_role=normalized_role or "",
                experience_level=exp_level or "unknown",
                experience_interpretation=exp_display or "Not specified",
                top_matched_skills=list(gap.get("matched_skills") or [])[:15],
            )
            ai_advice_structured = structured
            ai_advice = fallback

        # 8. Skill categorization and learning path
        missing_by_category = categorize_missing_skills(gap["missing_skills"])
        weakness_summary = _describe_weaknesses(missing_by_category)
        learning_path = generate_learning_path(gap["missing_skills"], exp_level if exp_level != "unknown" else None)

        predictive: dict = {
            "best_next_action": None,
            "time_aware_insights": [],
            "relevance_decay_model_note": "",
            "predictive_warnings": [],
            "predictive_opportunities": [],
            "career_insights_extra": {},
        }
        try:
            traj_ok = await predict_career_trajectory(
                self.session,
                resume_id=resume_id,
                target_role=normalized_role,
            )
            likely = list(traj_ok.get("likely_next_roles") or [])
            predictive = await build_predictive_gap_bundle(
                self.session,
                resume=resume,
                gap=gap,
                role_fits=role_rows,
                growth_map=growth_map,
                projected_delta=projected_delta,
                normalized_target=normalized_role,
                likely_next_roles=likely,
                weakness_summary=weakness_summary,
            )
        except Exception as exc:
            logger.warning("predictive career engine skipped resume_id=%d: %s", resume_id, exc)

        extra_ci = predictive.get("career_insights_extra") or {}
        insights_raw["headline_improving_vs_peers"] = extra_ci.get("headline_improving_vs_peers") or ""
        insights_raw["headline_trending_role"] = extra_ci.get("headline_trending_role") or ""
        insights_raw["headline_switch_timing"] = extra_ci.get("headline_switch_timing") or ""
        dl = list(insights_raw.get("detail_lines") or [])
        for line in (
            insights_raw["headline_improving_vs_peers"],
            insights_raw["headline_trending_role"],
            insights_raw["headline_switch_timing"],
        ):
            if line and line not in dl:
                dl.append(line)
        insights_raw["detail_lines"] = dl[:14]
        career_insights = CareerInsightsOut(**insights_raw)

        best_na_out: BestNextActionOut | None = None
        bna = predictive.get("best_next_action")
        if isinstance(bna, dict) and bna.get("type") and bna.get("reason"):
            try:
                best_na_out = BestNextActionOut(
                    type=bna["type"],
                    reason=str(bna["reason"]),
                    expected_impact_percent=int(max(0, min(100, int(bna.get("expected_impact_percent", 0))))),
                )
            except Exception:
                best_na_out = None

        try:
            await record_career_progress_snapshot(
                self.session,
                resume=resume,
                fit_score=float(gap["fit_percentage"]),
                skills_count=len(gap.get("resume_skills") or []),
                roles_considered=[str(r.get("role", "")) for r in role_rows[:12] if r.get("role")],
            )
            await self.session.commit()
        except Exception as exc:
            logger.warning("career_progress snapshot resume_id=%d: %s", resume_id, exc)
            await self.session.rollback()

        logger.info(
            "gap_analysis_event %s",
            {
                "event": "gap_analysis",
                "resume_id": resume_id,
                "resume_skills_count": len(gap.get("resume_skills") or []),
                "job_count": int(getattr(data_quality, "jobs_count", 0) or 0),
                "experience_years": int(exp_years or 0),
                "fallback_used": bool(job_fetch_notice),
                "data_source": data_source,
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            },
        )

        return ResumeGapOut(
            resume_skills=gap["resume_skills"],
            market_skill_count=gap["market_skill_count"],
            matched_skills=gap["matched_skills"],
            missing_skills=gap["missing_skills"],
            high_demand_missing_skills=[SkillDemandOut(**x) for x in gap["high_demand_missing_skills"]],
            fit_percentage=gap["fit_percentage"],
            gap_percentage=gap["gap_percentage"],
            projected_fit_percentage=projected_fit,
            scrape_summary={
                "total_new": scrape_result["total_new"],
                "total_cached": scrape_result["total_cached"],
                "portals": scrape_result["portals"],
                "errors": scrape_result["errors"],
                "links_parsed_total": scrape_result.get("links_parsed_total", 0),
                "market_scrape_degraded": scrape_result.get("market_scrape_degraded", False),
                "db_jobs_count": scrape_result.get("db_jobs_count", 0),
                "scrape_health": scrape_result.get("scrape_health"),
                "synthetic_fallback_inserted": synthetic_inserted,
            },
            market_source=gap.get("market_source"),
            demand_source=getattr(data_quality, "demand_source", None),
            matching_explanation=MATCHING_EXPLANATION,
            ai_advice=ai_advice,
            ai_advice_structured=ai_advice_structured,
            missing_skills_by_category=missing_by_category,
            weakness_summary=weakness_summary,
            learning_path=learning_path,
            data_quality=data_quality,
            job_fetch_notice=job_fetch_notice,
            target_role=normalized_role,
            experience_level=exp_level,
            experience_years=exp_years,
            experience_interpretation=exp_display,
            suggested_roles=_prioritize_user_target_in_suggested(
                suggested, normalized_role, user_specified_target_role
            )[:8],
            career_insights=career_insights,
            confidence=gap_conf,
            best_next_action=best_na_out,
            time_aware_insights=list(predictive.get("time_aware_insights") or []),
            relevance_decay_model_note=str(predictive.get("relevance_decay_model_note") or ""),
            predictive_warnings=list(predictive.get("predictive_warnings") or []),
            predictive_opportunities=list(predictive.get("predictive_opportunities") or []),
        )
