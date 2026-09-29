import asyncio
import json
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db import get_async_session
from app.models import Job, Resume
from app.services.live_job_registry import get_job as get_live_job_row, is_ephemeral_job_id
from app.schemas.match import (
    MatchResult,
    ResumeGapOut,
    SkillDemandOut,
    ResumeScoreOut,
    MissingSkillImpactOut,
    MarketTrendsOut,
    SkillTrendOut,
    RoleFitOut,
    SimulateSkillsBody,
    SimulateSkillsOut,
    SimulationStepOut,
    SkillTrendsEngineOut,
    CareerPathOut,
    JobFeedbackBody,
    GlobalInsightsOut,
    GlobalSkillRankOut,
    GlobalTransitionOut,
    RoleTransitionProbOut,
    CareerTrajectoryOut,
    CareerProgressOut,
    CareerProgressPointOut,
    LikelyNextRoleOut,
)
from app.services.match_service import MatchService
from app.services.resume_service import ResumeService, job_exists, resume_exists
from app.services.skill_service import (
    is_blocklisted_skill, is_plausible_skill_name,
    skill_demand_percentages, skill_trends, skill_trends_fastest_declining,
)
from app.services.career_path_service import build_career_path
from app.services.career_stats_service import (
    add_user_job_feedback,
    record_simulated_skill_stats,
)
from app.services.feedback_intelligence_service import on_job_feedback_recorded
from app.services.global_intel_service import build_global_insights_payload
from app.services.llm_service import (
    infer_role_cluster,
    is_llm_enabled,
    match_advice as llm_match_advice,
)
from app.services.career_progress_service import (
    fetch_progress_series,
    improvement_rate_per_week,
    insight_lines_for_progress,
    median_switch_weeks_hint,
    peer_improvement_percentile,
)
from app.services.gap_service import GapAnalysisService
from app.services.trajectory_service import predict_career_trajectory
from app.services.role_fit_service import suggest_roles_from_corpus
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/analysis", tags=["analysis"])


def _clean_job_title(title: str | None) -> str | None:
    """Remove LinkedIn boilerplate from job title for display."""
    if not title or not title.strip():
        return title
    t = title.strip()
    for sep in (
        "— You may also apply directly on company website .(linkedin)",
        "— You may also apply directly on company website (linkedin)",
        ".(linkedin)",
        "(linkedin)",
    ):
        if sep in t:
            t = t.split(sep)[0].strip()
    if t.endswith("—") or t.endswith(" -"):
        t = t[:-1].strip()
    return t if t else title.strip()


class ResumeGapBody(BaseModel):
    resume_id: int
    target_role: str | None = Field(None, max_length=100)
    experience_input: str | None = Field(None, max_length=100)


class TaskStatusOut(BaseModel):
    task_id: str
    status: str      # queued | in_progress | completed | failed | not_found
    message: str | None = None
    result: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Match endpoint (unchanged)
# ---------------------------------------------------------------------------

@router.get("/match", response_model=MatchResult)
async def match_resume_to_job(
    job_id: int = Query(...),
    resume_id: int = Query(...),
    include_demand: bool = Query(True),
    session: AsyncSession = Depends(get_async_session),
):
    job = await session.get(Job, job_id)
    if job is None and is_ephemeral_job_id(job_id):
        er = get_live_job_row(job_id)
        if er:
            job = SimpleNamespace(
                id=job_id,
                title=er.get("title"),
                description=er.get("description") or "",
            )
    if not job:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")
    resume_svc = ResumeService(session)
    resume, _ = await resume_svc.get_resume_with_skills(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail=f"Resume with id {resume_id} not found")

    service = MatchService(session)
    result = await service.compute_match(job_id, resume_id, include_demand=include_demand)
    ai_advice = None
    ai_advice_structured = None
    if is_llm_enabled() and job:
        rs = result["resume_score"]
        resume_text = (resume.raw_text or "").strip()[:3000]
        structured, fallback = await llm_match_advice(
            match_score=rs["total_score"],
            semantic=rs["semantic_score"],
            skill_overlap=rs["skill_overlap_score"],
            keyword=rs["keyword_coverage_score"],
            matched_skills=result["matched_skills"],
            missing_skills=result["missing_skills"],
            job_title=job.title or "",
            job_description=(job.description or "")[:2000],
            resume_text=resume_text,
            role_cluster=infer_role_cluster(job.title or ""),
        )
        ai_advice_structured = structured
        ai_advice = fallback
    return MatchResult(
        job_id=result["job_id"],
        job_external_id=result["job_external_id"],
        job_title=_clean_job_title(result["job_title"]) or result["job_title"],
        match_percentage=result["match_percentage"],
        match_mode=result.get("match_mode"),
        resume_score=ResumeScoreOut(**result["resume_score"]),
        matched_skills=result["matched_skills"],
        missing_skills=result["missing_skills"],
        semantic_similarity=result["semantic_similarity"],
        high_demand_missing_skills=[SkillDemandOut(**x) for x in result["high_demand_missing_skills"]],
        missing_skill_impacts=[MissingSkillImpactOut(**x) for x in result.get("missing_skill_impacts", [])],
        top_positive_factors=result.get("top_positive_factors", []),
        top_negative_factors=result.get("top_negative_factors", []),
        ai_advice=ai_advice,
        ai_advice_structured=ai_advice_structured,
        match_explanation=result.get("match_explanation") or "",
        confidence=result.get("confidence"),
    )


# ---------------------------------------------------------------------------
# Skill demand + market trends (unchanged)
# ---------------------------------------------------------------------------

@router.get("/skill-demand", response_model=list[SkillDemandOut])
async def get_skill_demand(session: AsyncSession = Depends(get_async_session)):
    rows = await skill_demand_percentages(session)
    return [
        SkillDemandOut(skill_id=s.id, skill_name=s.name, category=s.category, job_count=cnt, demand_percentage=pct)
        for s, cnt, pct in rows
        if not is_blocklisted_skill(s.name) and is_plausible_skill_name(s.name)
    ]


@router.get("/suggest-roles", response_model=list[RoleFitOut])
async def suggest_roles(
    resume_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_async_session),
):
    """Top 3 role titles ranked by resume–job embedding similarity (corpus + scraped jobs)."""
    rows = await suggest_roles_from_corpus(session, resume_id)
    return [
        RoleFitOut(role=r["role"], fit=r["fit"], fit_reason=r.get("fit_reason") or "")
        for r in rows
    ]


@router.post("/simulate-skills", response_model=SimulateSkillsOut)
async def simulate_skills(
    body: SimulateSkillsBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Project market fit if the candidate adds the given skills (no DB write)."""
    if not await resume_exists(session, body.resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    svc = MatchService(session)
    if body.multi_step:
        out = await svc.project_fit_multistep(
            body.resume_id,
            body.skills_to_add,
            body.target_role,
        )
    else:
        out = await svc.project_fit_with_skills(
            body.resume_id,
            body.skills_to_add,
            body.target_role,
        )
    await record_simulated_skill_stats(body.skills_to_add)
    steps_raw = out.get("steps") or []
    steps = [SimulationStepOut(**s) for s in steps_raw] if steps_raw else None
    return SimulateSkillsOut(
        new_fit=out["new_fit"],
        previous_fit=out["previous_fit"],
        improvement=out["improvement"],
        skills_added=out["skills_added"],
        market_skill_count=out.get("market_skill_count", 0),
        steps=steps,
    )


@router.post("/job-feedback")
async def post_job_feedback(
    body: JobFeedbackBody,
    session: AsyncSession = Depends(get_async_session),
):
    """Log viewed / clicked / applied for learning-loop match boosting."""
    if body.action not in ("viewed", "clicked", "applied"):
        raise HTTPException(status_code=400, detail="action must be viewed, clicked, or applied")
    if not await resume_exists(session, body.resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    if not await job_exists(session, body.job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    await add_user_job_feedback(
        session,
        resume_id=body.resume_id,
        job_id=body.job_id,
        action=body.action,
    )
    await on_job_feedback_recorded(
        session,
        resume_id=body.resume_id,
        job_id=body.job_id,
        action=body.action,
    )
    await session.commit()
    return {"ok": True}


@router.get("/skill-trends", response_model=SkillTrendsEngineOut)
async def get_skill_trends_engine(
    weeks: int = Query(8, ge=2, le=52),
    limit: int = Query(20, ge=5, le=50),
    session: AsyncSession = Depends(get_async_session),
):
    """Fastest-growing vs declining skills from weekly job_skill aggregates."""
    fastest, declining, weeks_with_data = await skill_trends_fastest_declining(
        session, weeks=weeks, limit=limit,
    )
    fastest = [
        t for t in fastest
        if not is_blocklisted_skill(t.get("skill_name") or "")
        and is_plausible_skill_name(t.get("skill_name") or "")
    ]
    declining = [
        t for t in declining
        if not is_blocklisted_skill(t.get("skill_name") or "")
        and is_plausible_skill_name(t.get("skill_name") or "")
    ]
    return SkillTrendsEngineOut(
        fastest_growing_skills=[SkillTrendOut(**t) for t in fastest],
        declining_skills=[SkillTrendOut(**t) for t in declining],
        weeks_with_data=weeks_with_data,
    )


@router.get("/career-path", response_model=CareerPathOut)
async def get_career_path(
    resume_id: int = Query(..., ge=1),
    current_role: str | None = Query(None, max_length=120),
    session: AsyncSession = Depends(get_async_session),
):
    """Next roles from role graph plus missing skills toward the first suggested hop."""
    if not await resume_exists(session, resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    payload = await build_career_path(session, resume_id=resume_id, current_role=current_role)
    rt = [RoleTransitionProbOut(**x) for x in payload.get("role_transitions") or []]
    return CareerPathOut(
        current_role=payload["current_role"],
        next_roles=payload.get("next_roles") or [],
        role_transitions=rt,
        required_skills=payload.get("required_skills") or [],
    )


@router.get("/global-insights", response_model=GlobalInsightsOut)
async def get_global_insights(session: AsyncSession = Depends(get_async_session)):
    """Cross-user aggregates: popular skills/roles, inferred transitions, adoption velocity."""
    raw = await build_global_insights_payload(session)
    return GlobalInsightsOut(
        top_skills=[GlobalSkillRankOut(**x) for x in raw["top_skills"]],
        emerging_roles=[GlobalSkillRankOut(**x) for x in raw["emerging_roles"]],
        common_transitions=[GlobalTransitionOut(**x) for x in raw["common_transitions"]],
        fastest_adopted_skills=raw["fastest_adopted_skills"],
        trend_weeks_available=raw["trend_weeks_available"],
    )


@router.get("/career-trajectory", response_model=CareerTrajectoryOut)
async def get_career_trajectory(
    resume_id: int = Query(..., ge=1),
    target_role: str | None = Query(None, max_length=120),
    session: AsyncSession = Depends(get_async_session),
):
    """Predict likely next roles, time-to-bridge weeks, and stagnation risk (heuristic)."""
    if not await resume_exists(session, resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    try:
        raw = await predict_career_trajectory(
            session, resume_id=resume_id, target_role=target_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CareerTrajectoryOut(
        current_role=raw["current_role"],
        likely_next_roles=[LikelyNextRoleOut(**x) for x in raw.get("likely_next_roles") or []],
        risk_of_stagnation=float(raw.get("risk_of_stagnation") or 0.4),
    )


@router.get("/career-progress", response_model=CareerProgressOut)
async def get_career_progress(
    resume_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_async_session),
):
    """Fit snapshots over time for the resume owner's account + improvement rate."""
    resume_svc = ResumeService(session)
    resume, _ = await resume_svc.get_resume_with_skills(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id is None:
        return CareerProgressOut(
            points=[],
            improvement_rate_per_week=0.0,
            peer_improvement_percentile=50,
            insight_lines=[
                "No journey snapshots yet — authenticate and run gap analysis to build your progress graph.",
            ],
        )
    points_orm = await fetch_progress_series(
        session, user_id=resume.user_id, resume_id=resume_id, limit=120,
    )
    rate = improvement_rate_per_week(points_orm)
    peer_pct = peer_improvement_percentile(rate)
    switch_w = await median_switch_weeks_hint(session)
    lines = insight_lines_for_progress(
        improvement_per_week=rate,
        peer_pct=peer_pct,
        n_points=len(points_orm),
        median_switch_weeks=switch_w,
    )
    points_out = [
        CareerProgressPointOut(
            snapshot_at=p.snapshot_at,
            fit_score=p.fit_score,
            skills_count=p.skills_count,
            roles_considered=list(p.roles_considered or []),
        )
        for p in points_orm
    ]
    return CareerProgressOut(
        points=points_out,
        improvement_rate_per_week=rate,
        peer_improvement_percentile=peer_pct,
        insight_lines=lines,
    )


@router.get("/market-trends", response_model=MarketTrendsOut)
async def get_market_trends(
    weeks: int = 8,
    top_emerging_n: int = 15,
    resume_id: int | None = Query(None, description="If set, show trends only for skills present on this resume"),
    session: AsyncSession = Depends(get_async_session),
):
    """Time-based skill trend analytics: weekly growth, volatility index, top emerging skills."""
    trends_list, top_emerging_list, weeks_with_data = await skill_trends(
        session, weeks=weeks, top_emerging_n=top_emerging_n
    )
    trends_list = [
        t for t in trends_list
        if not is_blocklisted_skill(t.get("skill_name") or "") and is_plausible_skill_name(t.get("skill_name") or "")
    ]
    top_emerging_list = [
        t for t in top_emerging_list
        if not is_blocklisted_skill(t.get("skill_name") or "") and is_plausible_skill_name(t.get("skill_name") or "")
    ]
    if resume_id is not None:
        resume_svc = ResumeService(session)
        _, resume_skill_names = await resume_svc.get_resume_with_skills(resume_id)
        if resume_skill_names:
            resume_skills_lower = {s.strip().lower() for s in resume_skill_names if s and s.strip()}
            trends_list = [t for t in trends_list if (t.get("skill_name") or "").strip().lower() in resume_skills_lower]
            top_emerging_list = [t for t in top_emerging_list if (t.get("skill_name") or "").strip().lower() in resume_skills_lower]
    return MarketTrendsOut(
        trends=[SkillTrendOut(**t) for t in trends_list],
        top_emerging=[SkillTrendOut(**t) for t in top_emerging_list],
        weeks_with_data=weeks_with_data,
    )


# ---------------------------------------------------------------------------
# Resume gap analysis — synchronous inline execution
# ---------------------------------------------------------------------------

@router.post("/resume-gap")
@limiter.limit("1/10 seconds")
async def analyze_resume_gap(
    request: Request,
    body: ResumeGapBody,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Run gap analysis inline and return ResumeGapOut (HTTP 200).
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    try:
        result = await GapAnalysisService(session, arq_pool=arq_pool).analyze(
            body.resume_id,
            target_role=body.target_role,
            experience_input=body.experience_input,
        )
    except ValueError as exc:
        http_status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=http_status, detail=str(exc))
    return result


@router.post("/resume-gap-stream")
@limiter.limit("1/10 seconds")
async def analyze_resume_gap_stream(
    request: Request,
    body: ResumeGapBody,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Server-Sent Events (SSE): `type=log` (message only) and `type=progress` (percent + message),
    then a final `result` payload. Same analysis as POST /resume-gap.
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(ev: dict) -> None:
        await queue.put(("progress", ev))

    async def runner() -> None:
        try:
            result = await GapAnalysisService(session, arq_pool=arq_pool).analyze(
                body.resume_id,
                target_role=body.target_role,
                experience_input=body.experience_input,
                on_progress=on_progress,
            )
            await queue.put(("done", result))
        except ValueError as exc:
            await queue.put(("error", str(exc)))
        except Exception as exc:
            logger.exception("resume-gap-stream failed")
            await queue.put(("error", str(exc)))

    async def event_stream():
        task = asyncio.create_task(runner())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "progress":
                    if "percent" in payload:
                        yield f"data: {json.dumps({'type': 'progress', 'percent': payload['percent'], 'message': payload.get('message', '')})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'log', 'message': payload.get('message', '')})}\n\n"
                    await asyncio.sleep(0)
                elif kind == "done":
                    data = payload.model_dump(mode="json")  # ResumeGapOut
                    yield f"data: {json.dumps({'type': 'result', 'payload': data})}\n\n"
                    break
                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'detail': str(payload)})}\n\n"
                    break
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Task status endpoint
# ---------------------------------------------------------------------------

@router.get("/status/{task_id}", response_model=TaskStatusOut)
async def get_task_status(task_id: str, request: Request):
    """
    Poll the status of a background gap analysis task.

    Possible status values:
      queued       — waiting in ARQ queue
      in_progress  — worker is currently executing
      completed    — finished; result is in the response
      failed       — task threw an exception; error message included
      not_found    — task_id unknown or result has expired (TTL = 1 hour)

    Fix: previously called create_pool() on every poll, creating a brand-new
    Redis connection pool per request (~50/s under normal polling load).
    Now reuses app.state.arq_pool that was created once at startup.
    """
    # Reuse the pool that was created at startup — never call create_pool() per request
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Background job system unavailable (Redis not connected)",
        )

    try:
        from arq.jobs import Job, JobStatus

        job = Job(task_id, arq_pool)
        job_status = await job.status()

        if job_status == JobStatus.not_found:
            return TaskStatusOut(task_id=task_id, status="not_found", message="Task not found or result has expired.")

        if job_status in (JobStatus.queued, JobStatus.deferred):
            return TaskStatusOut(task_id=task_id, status="queued")

        if job_status == JobStatus.in_progress:
            return TaskStatusOut(task_id=task_id, status="in_progress")

        if job_status == JobStatus.complete:
            info = await job.result_info()
            payload: dict | None = info.result if info else None
            if payload and isinstance(payload, dict):
                inner_status = payload.get("status", "completed")
                return TaskStatusOut(
                    task_id=task_id,
                    status=inner_status,
                    result=payload.get("result"),
                    error=payload.get("error"),
                )
            return TaskStatusOut(task_id=task_id, status="completed")

        return TaskStatusOut(task_id=task_id, status=str(job_status))

    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not fetch task status: {exc}")
    # No finally/close — we must NOT close the shared pool here
