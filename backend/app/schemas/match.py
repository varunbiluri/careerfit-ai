from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class DataQualityMeta(BaseModel):
    """
    Metadata about the quality and freshness of the job-market data used in
    this gap analysis.  Surfaces as ``data_quality`` in ResumeGapOut so the
    frontend can show a "last updated X hours ago" indicator and a completeness
    badge.
    """
    jobs_count: int = Field(0, ge=0, description="Total jobs in DB at analysis time")
    freshness_hours: float = Field(
        999.0, ge=0,
        description="Hours since last scrape completed (999 = never scraped)"
    )
    completeness_score: float = Field(
        0.0, ge=0, le=1,
        description="Fraction of DB jobs that have title + description + company (0–1)"
    )
    is_fresh: bool = Field(False, description="True when freshness_hours < configured threshold")
    scraped_at: datetime | None = Field(None, description="UTC timestamp of last completed scrape")
    source: str = Field(
        "unknown",
        description=(
            "fresh_cache — re-used existing data within freshness window; "
            "live_scrape — just scraped; "
            "concurrent_lock — another scrape was running; "
            "synthetic — no real jobs, used skills dictionary fallback"
        ),
    )
    quality_band: Literal["high", "medium", "low"] = Field(
        "medium",
        description="high >50 live jobs; medium sparse; low fallback / scrape failure",
    )
    demand_source: Literal["real", "corpus", "synthetic"] = Field(
        "real",
        description="real — mostly scraped/API jobs; corpus — curated job_corpus.json; synthetic — tiny offline fallback only",
    )


class SkillDemandOut(BaseModel):
    skill_id: int
    skill_name: str
    category: str | None
    job_count: int
    demand_percentage: float = Field(..., ge=0, le=100)


class MissingSkillImpactOut(BaseModel):
    """Explainable AI: contribution of each missing skill to score drop and hypothetical score if added."""
    skill_name: str
    score_drop: float = Field(..., ge=0, description="Points lost because this skill is missing")
    score_if_added: float = Field(..., ge=0, le=100, description="Hypothetical total score if this skill were added")
    demand_percentage: float | None = Field(None, ge=0, le=100, description="Share of jobs that list this skill")
    demand_penalty_impact: float | None = Field(None, ge=0, description="Score drop weighted by demand (score_drop × demand%)")


class ResumeScoreOut(BaseModel):
    total_score: float = Field(..., ge=0, le=100)
    semantic_score: float = Field(..., ge=0, le=100)
    skill_overlap_score: float = Field(..., ge=0, le=100)
    keyword_coverage_score: float = Field(..., ge=0, le=100)
    weights_used: dict[str, float]
    demand_penalty_raw: float = Field(0, ge=0, le=100, description="D: average demand % of missing skills")
    demand_penalty_points: float = Field(0, le=0, description="Penalty applied: -0.2*D (e.g. -6.0)")
    # Replaced fake 95% CI (SE=3/sqrt(n)) with honest uncertainty heuristic.
    # uncertainty_score: 0 = high confidence (many reference skills), 30 = low confidence (few skills).
    uncertainty_score: float = Field(0, ge=0, le=30, description="Score uncertainty (0=confident, 30=sparse reference data)")
    score_reason: str = Field("", description="Human-readable explanation of main score drivers")
    projected_total_score: float | None = Field(
        None, ge=0, le=100,
        description="Hypothetical score after closing top missing-skill gaps (upper bound estimate)",
    )
    projection_message: str | None = Field(
        None,
        description="UX copy e.g. If you learn top skills → ~N% fit",
    )
    scoring_mode: str | None = Field(
        None,
        description="live — normal formula; fallback — no market data, estimated score",
    )
    scoring_reason: str | None = Field(
        None,
        description="e.g. no_market_data when DB has zero jobs",
    )
    behavior_boost: float = Field(
        0.0,
        ge=0,
        le=10,
        description="Additive points from jobs you previously clicked/applied to (skill overlap)",
    )
    behavior_score_normalized: float = Field(
        0.0,
        ge=0,
        le=0.1,
        description="behavior_boost / 100 — comparable to spec's 0–0.1 scale",
    )
    base_score_before_behavior: float | None = Field(
        None,
        description="Formula total before behavior boost (when boost applied)",
    )
    profile_role_boost: float = Field(
        0.0,
        ge=0,
        le=12,
        description="Extra points when job title matches roles learned from your clicks/applies",
    )
    confidence: str | None = Field(
        None,
        description="Trust band: high | medium | low (from job corpus size, skill coverage, embedding decisiveness)",
    )
    why_lines: list[str] = Field(
        default_factory=list,
        description="Deterministic explanation of how the score was composed",
    )


class RewrittenBulletOut(BaseModel):
    """One resume bullet rewritten for the target job."""
    original: str = Field(..., description="Original bullet from resume")
    rewritten: str = Field(..., description="Rewritten bullet tailored to the job")


class MatchAdviceStructuredOut(BaseModel):
    """Structured match advice from LLM (bullet improvements, rewritten bullets, metrics)."""
    fit_level: str = Field("", description="strong | moderate | needs_work")
    fit_reason: str = Field("", description="One sentence why")
    highlights: list[str] = Field(default_factory=list, description="What to emphasize for this role")
    bullet_improvements: list[str] = Field(default_factory=list, description="Suggested bullet improvements")
    rewritten_bullets: list[RewrittenBulletOut] = Field(default_factory=list, description="Resume bullets rewritten for this job")
    measurable_metrics: list[str] = Field(default_factory=list, description="Suggested metrics to add (e.g. Reduced latency by 20%)")
    improve_skills: list[str] = Field(default_factory=list, description="Missing skills to add for this role")
    priority: list[str] = Field(default_factory=list, description="Ordered actions / skills (card UI)")
    highlight: str = Field("", description="Single headline highlight for card UI")
    next_step: str = Field("", description="One concrete next step for card UI")


class GapAdviceStructuredOut(BaseModel):
    """Structured gap advice from LLM."""
    prioritize: list[str] = Field(default_factory=list, description="Skills to learn first (from high-demand missing)")
    highlight_how: str = Field("", description="How to describe matched skills in interviews")
    next_step: str = Field("", description="One concrete action: course, project, or tool")
    bullet_improvements: list[str] = Field(default_factory=list, description="Suggested bullet improvements")
    measurable_metrics: list[str] = Field(default_factory=list, description="Suggested metrics to add to resume")
    priority: list[str] = Field(default_factory=list, description="Same as prioritize (structured cards)")
    highlight: str = Field("", description="Same as highlight_how (structured cards)")
    project_ideas: list[str] = Field(
        default_factory=list,
        description="Concrete portfolio projects aligned to target role",
    )
    learning_path: list[str] = Field(
        default_factory=list,
        description="LLM-suggested ordered learning steps (distinct from heuristic resume-gap learning_path)",
    )


class MatchResult(BaseModel):
    job_id: int
    job_external_id: str
    job_title: str | None
    match_percentage: float = Field(..., ge=0, le=100)
    match_mode: str | None = Field(None, description="live | fallback")
    resume_score: ResumeScoreOut
    matched_skills: list[str]
    missing_skills: list[str]
    semantic_similarity: float = Field(..., ge=0, le=1)
    high_demand_missing_skills: list[SkillDemandOut] = []
    missing_skill_impacts: list[MissingSkillImpactOut] = Field(default_factory=list, description="Explainable: score drop and score-if-added per missing skill")
    top_positive_factors: list[str] = Field(default_factory=list, description="What is driving the score up (e.g. 'High semantic similarity (82%)')")
    top_negative_factors: list[str] = Field(default_factory=list, description="What is dragging the score down (e.g. 'Missing high-demand skills: AWS, GCP')")
    ai_advice: str | None = None  # Fallback plain-text advice
    ai_advice_structured: MatchAdviceStructuredOut | None = None  # Structured JSON advice when LLM returns valid JSON
    match_explanation: str = Field(
        "",
        description="Single string joining why_lines — answers 'Why this score?'",
    )
    confidence: str | None = Field(
        None,
        description="Same band as resume_score.confidence — surfaced at top level for clients",
    )


# Short explanation for "How we match with the market" (exact + optional semantic matching)
MATCHING_EXPLANATION = (
    "We compare your resume skills to skills extracted from job postings. "
    "A skill counts as matched if names align exactly, share the same embedding cluster "
    "(cosine similarity ≥ ~0.85, transitive groups), or match after normalization. "
    "Missing skills are those the market asks for that did not match any of your skills."
)


class CareerInsightsOut(BaseModel):
    headline_closest_role: str = ""
    headline_roi_skill: str = ""
    headline_strongest_domain: str = ""
    headline_ahead_of_peers: str = Field(
        "",
        description="Percentile-style benchmark vs a fixed median reference (explainable heuristic)",
    )
    comparison_vs_median: str = Field("", description="User fit delta vs median benchmark")
    headline_roi_percent: str = Field(
        "",
        description="Estimated fit lift from closing highlighted gaps, e.g. +18%",
    )
    headline_improving_vs_peers: str = Field(
        "",
        description="Journey-based improvement vs reference curve (snapshots)",
    )
    headline_trending_role: str = Field("", description="Corpus / embedding drift toward a role label")
    headline_switch_timing: str = Field(
        "",
        description="Aggregate transition timing hint from global stats",
    )
    detail_lines: list[str] = Field(default_factory=list)


class BestNextActionOut(BaseModel):
    type: Literal["learn_skill", "apply_jobs", "switch_role"]
    reason: str
    expected_impact_percent: int = Field(..., ge=0, le=100, description="Heuristic upside band for UX")


class ResumeGapOut(BaseModel):
    resume_skills: list[str] = []
    market_skill_count: int = 0
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    high_demand_missing_skills: list[SkillDemandOut] = []
    fit_percentage: float = Field(..., ge=0, le=100)
    gap_percentage: float = Field(..., ge=0, le=100)
    projected_fit_percentage: float | None = Field(
        None,
        ge=0,
        le=100,
        description="Approximate market fit if top high-demand gaps are closed",
    )
    scrape_summary: dict | None = None
    job_title: str | None = None
    market_source: str | None = None  # scraped | corpus | synthetic (aligned with demand_source / job rows)
    demand_source: str | None = Field(
        None,
        description="Duplicate of data_quality.demand_source for clients that do not read nested meta",
    )
    matching_explanation: str | None = None  # How we match with the market (for UI tooltip/expandable)
    ai_advice: str | None = None
    ai_advice_structured: GapAdviceStructuredOut | None = None
    # Phase 3: skill categorization
    missing_skills_by_category: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Missing skills grouped by category, e.g. {'Cloud': ['AWS', 'GCP']}"
    )
    weakness_summary: list[str] = Field(
        default_factory=list,
        description="e.g. ['You are weak in Cloud skills (AWS, GCP missing)']"
    )
    learning_path: list[str] = Field(
        default_factory=list,
        description="Ordered learning steps for missing skills, e.g. ['Learn Python (Programming)', 'Build Cloud foundation: AWS, GCP (+1 more)']"
    )
    data_quality: DataQualityMeta | None = Field(
        None,
        description="Quality and freshness metadata for the job-market data used in this analysis"
    )
    job_fetch_notice: str | None = Field(
        None,
        description="UX banner when live scrape failed but cached jobs exist (or empty corpus)",
    )
    target_role: str | None = Field(None, description="Normalized target job title used for this analysis")
    experience_level: str | None = Field(
        None,
        description="Parsed coarse level: entry | junior | mid | senior | unknown",
    )
    experience_years: int | None = Field(None, description="Parsed years of experience when inferable")
    experience_interpretation: str | None = Field(
        None,
        description='Human-readable, e.g. "Junior (2 years)"',
    )
    suggested_roles: list[str] = Field(
        default_factory=list,
        description="Heuristic role suggestions from resume text (for UI chips)",
    )
    career_insights: CareerInsightsOut | None = Field(
        None,
        description="Deterministic advisor copy: closest role, ROI skill, strongest domain",
    )
    confidence: str | None = Field(
        None,
        description="high | medium | low — trust in gap numbers given corpus size and quality band",
    )
    best_next_action: BestNextActionOut | None = Field(
        None,
        description="Single highest-ROI recommendation (deterministic ranking)",
    )
    time_aware_insights: list[str] = Field(
        default_factory=list,
        description="Time-bounded skill learning and inaction / decay estimates",
    )
    relevance_decay_model_note: str = Field(
        "",
        description="Plain-language formula for skill relevance decay (no ML)",
    )
    predictive_warnings: list[str] = Field(default_factory=list)
    predictive_opportunities: list[str] = Field(default_factory=list)


class SuggestedRoleOut(BaseModel):
    job_title: str
    relevance: int


class RoleFitOut(BaseModel):
    """Top role recommendations from resume vs job corpus embeddings."""
    role: str = Field(..., description="Job title / role label")
    fit: float = Field(..., ge=0, le=100, description="Cosine-based fit score 0–100")
    fit_reason: str = Field(
        "",
        description="Short explanation of why this role was recommended",
    )


class SimulationStepOut(BaseModel):
    step: int = Field(..., ge=1)
    skills: list[str] = Field(default_factory=list)
    fit: float = Field(..., ge=0, le=100)
    weeks_estimate: int = Field(2, ge=1, le=52, description="Rough weeks to reach this step")


class SimulateSkillsBody(BaseModel):
    resume_id: int
    skills_to_add: list[str] = Field(default_factory=list, max_length=40)
    target_role: str | None = Field(None, max_length=100)
    multi_step: bool = Field(False, description="If true, return stepped plan with cumulative fit")


class SimulateSkillsOut(BaseModel):
    new_fit: float = Field(..., ge=0, le=100)
    previous_fit: float = Field(..., ge=0, le=100)
    improvement: float
    skills_added: list[str] = Field(default_factory=list)
    market_skill_count: int = 0
    steps: list[SimulationStepOut] | None = Field(
        None,
        description="Populated when multi_step=true",
    )


class JobFeedbackBody(BaseModel):
    resume_id: int = Field(..., ge=1)
    job_id: int = Field(..., ge=1)
    action: str = Field(..., description="viewed | clicked | applied")


# --- Market trend analytics ---

class SkillTrendOut(BaseModel):
    """Time-based skill trend: demand, weekly growth, volatility."""
    skill_id: int
    skill_name: str
    category: str | None
    job_count: int
    demand_percentage: float
    weekly_growth_pct: float | None = Field(None, description="Week-over-week growth % (last 2 weeks)")
    volatility_index: float = Field(0, ge=0, description="Coefficient of variation of weekly job counts (higher = more volatile)")


class MarketTrendsOut(BaseModel):
    """Market trend analytics: skill trends and top emerging skills."""
    trends: list[SkillTrendOut] = Field(default_factory=list, description="All skills with trend metrics")
    top_emerging: list[SkillTrendOut] = Field(default_factory=list, description="Skills with positive weekly growth, sorted by growth")
    weeks_with_data: int = Field(0, ge=0, description="Number of distinct weeks with job data; need >= 2 for weekly growth and volatility")


class SkillTrendsEngineOut(BaseModel):
    """Fastest-growing vs declining skills (weekly job_skill buckets)."""
    fastest_growing_skills: list[SkillTrendOut] = Field(default_factory=list)
    declining_skills: list[SkillTrendOut] = Field(default_factory=list)
    weeks_with_data: int = Field(0, ge=0)


class RoleTransitionProbOut(BaseModel):
    role: str
    probability: float = Field(..., ge=0, le=1, description="Share of outbound transition mass (graph prior + learned stats)")


class CareerPathOut(BaseModel):
    current_role: str
    next_roles: list[str] = Field(default_factory=list)
    role_transitions: list[RoleTransitionProbOut] = Field(
        default_factory=list,
        description="Same as next_roles but with normalized transition probabilities",
    )
    required_skills: list[str] = Field(default_factory=list)


class GlobalSkillRankOut(BaseModel):
    name: str
    score: float


class GlobalTransitionOut(BaseModel):
    from_role: str
    to_role: str
    weight: int = Field(..., ge=1)


class GlobalInsightsOut(BaseModel):
    top_skills: list[GlobalSkillRankOut] = Field(
        default_factory=list,
        description="Most interaction-weighted skills across all users (clicks/applies)",
    )
    emerging_roles: list[GlobalSkillRankOut] = Field(
        default_factory=list,
        description="Roles receiving the most weighted interest from all users",
    )
    common_transitions: list[GlobalTransitionOut] = Field(
        default_factory=list,
        description="Aggregate role→role moves inferred from sequential job engagement",
    )
    fastest_adopted_skills: list[dict] = Field(
        default_factory=list,
        description="Skills with strongest positive weekly growth in job postings (when history exists)",
    )
    trend_weeks_available: int = Field(0, ge=0)


class LikelyNextRoleOut(BaseModel):
    role: str
    probability: float = Field(..., ge=0, le=1)
    time_estimate_weeks: int = Field(..., ge=1, le=104)


class CareerTrajectoryOut(BaseModel):
    current_role: str
    likely_next_roles: list[LikelyNextRoleOut] = Field(default_factory=list)
    risk_of_stagnation: float = Field(..., ge=0, le=1)


class CareerProgressPointOut(BaseModel):
    snapshot_at: datetime
    fit_score: float
    skills_count: int
    roles_considered: list[str] = Field(default_factory=list)


class CareerProgressOut(BaseModel):
    points: list[CareerProgressPointOut] = Field(default_factory=list)
    improvement_rate_per_week: float = Field(0.0, description="Δ fit / Δ weeks across series")
    peer_improvement_percentile: int = Field(50, ge=0, le=100)
    insight_lines: list[str] = Field(default_factory=list)
