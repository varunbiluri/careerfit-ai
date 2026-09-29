from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user_optional
from app.core.limiter import limiter
from app.db import get_async_session
from app.models import Resume, ResumeSkill, Skill
from app.models.user import User
from app.schemas.resume import ResumeOut, ResumeAnalysisOut, SuggestedRolesOut
from app.services.live_resume_registry import is_ephemeral_resume_id, update_resume as registry_patch_resume
from app.services.skill_service import filter_technical_skills_only
from app.services.resume_service import ResumeService, suggest_roles_from_resume
from app.services.llm_service import is_llm_enabled, resume_summary as llm_resume_summary

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _allowed_file(filename: str) -> bool:
    return bool(filename and filename.lower().endswith(".pdf"))


@router.get("/", response_model=list[ResumeOut])
async def list_resumes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
):
    """
    List resumes. When authenticated, returns only the current user's resumes.
    When unauthenticated, returns all resumes (legacy behaviour for local dev).
    """
    # selectinload replaces the previous N+1 loop (1 SELECT per resume for skills).
    # SQLAlchemy now issues exactly 2 queries: one for resumes, one for all skills
    # linked to those resumes — regardless of result-set size.
    stmt = (
        select(Resume)
        .options(selectinload(Resume.resume_skills).selectinload(ResumeSkill.skill))
        .order_by(Resume.id.desc())
        .offset(skip)
        .limit(limit)
    )
    if current_user is not None:
        stmt = stmt.where(Resume.user_id == current_user.id)
    settings = get_settings()
    if not settings.persist_resumes:
        from app.services.live_resume_registry import list_resumes_for_user

        rows = list_resumes_for_user(current_user.id if current_user else None)
        rows = rows[skip : skip + limit]
        return [
            ResumeOut(
                id=int(r["id"]),
                filename=str(r["filename"]),
                candidate_name=r.get("candidate_name"),
                created_at=r["created_at"],
                skill_names=filter_technical_skills_only(list(r.get("skill_names") or [])),
                ai_summary=r.get("ai_summary"),
            )
            for r in rows
        ]
    resumes = (await session.execute(stmt)).scalars().all()
    return [
        ResumeOut(
            id=r.id,
            filename=r.filename,
            candidate_name=r.candidate_name,
            created_at=r.created_at,
            skill_names=filter_technical_skills_only(
                [rs.skill.name for rs in r.resume_skills]
            ),
            ai_summary=r.ai_summary,
        )
        for r in resumes
    ]


@router.post("/upload", response_model=ResumeOut)
@limiter.limit("5/minute")
async def upload_resume(
    request: Request,                      # required by slowapi
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
) -> ResumeOut:
    """
    Upload a PDF resume. Rate-limited to 5 uploads per minute per IP.
    When a valid JWT is provided, the resume is linked to the authenticated user.
    """
    if not file.filename or not _allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large. Max {settings.max_upload_mb} MB")
    service = ResumeService(session)
    resume = await service.create_resume(
        filename=file.filename,
        file_content=content,
        user_id=current_user.id if current_user else None,
    )
    if get_settings().persist_resumes:
        await session.commit()
        stmt = (
            select(Skill.name)
            .join(ResumeSkill, ResumeSkill.skill_id == Skill.id)
            .where(ResumeSkill.resume_id == resume.id)
        )
        skill_names = filter_technical_skills_only(
            list((await session.execute(stmt)).scalars().all())
        )
    else:
        _, skill_names = await service.get_resume_with_skills(resume.id)
    return ResumeOut(
        id=resume.id,
        filename=resume.filename,
        candidate_name=resume.candidate_name,
        created_at=resume.created_at,
        skill_names=skill_names,
        ai_summary=resume.ai_summary,
    )


@router.post("/{resume_id}/generate-summary")
async def generate_resume_summary(
    resume_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
):
    """Generate or regenerate AI summary for the resume (requires Ollama)."""
    if not is_llm_enabled():
        raise HTTPException(
            status_code=503,
            detail="Local LLM is not configured. Set LLM_BASE_URL (e.g. Ollama).",
        )
    service = ResumeService(session)
    resume, _ = await service.get_resume_with_skills(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _check_resume_access(resume, current_user)
    raw = resume.raw_text or ""
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Resume has no text to summarize")
    summary = await llm_resume_summary(raw)
    if not summary:
        raise HTTPException(
            status_code=503,
            detail="LLM did not return a summary. Check Ollama is running and model is available.",
        )
    if is_ephemeral_resume_id(resume_id):
        registry_patch_resume(resume_id, ai_summary=summary)
    else:
        resume.ai_summary = summary
        await session.commit()
    return {"id": resume.id, "ai_summary": summary}


@router.get("/{resume_id}/suggest-roles", response_model=SuggestedRolesOut)
async def suggest_roles_endpoint(
    resume_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
):
    service = ResumeService(session)
    resume, _names = await service.get_resume_with_skills(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _check_resume_access(resume, current_user)
    roles = suggest_roles_from_resume(resume.raw_text or "")
    return SuggestedRolesOut(roles=roles)


@router.get("/{resume_id}", response_model=ResumeAnalysisOut)
async def get_resume(
    resume_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
):
    service = ResumeService(session)
    resume, skill_names = await service.get_resume_with_skills(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    _check_resume_access(resume, current_user)
    return ResumeAnalysisOut(
        resume=ResumeOut(
            id=resume.id,
            filename=resume.filename,
            candidate_name=resume.candidate_name,
            created_at=resume.created_at,
            skill_names=skill_names,
            ai_summary=resume.ai_summary,
        ),
        extracted_skills=skill_names,
        raw_text_length=len(resume.raw_text or ""),
    )


def _check_resume_access(resume: Resume | object, current_user: Optional[User]) -> None:
    """
    Enforce user isolation on user-owned resumes.

    Security fix: the previous version allowed unauthenticated callers to
    access any resume "for backwards compat in dev". This is a sequential
    ID enumeration vulnerability — anyone could fetch every user's full
    resume text via GET /resumes/1, /resumes/2, etc. without credentials.
    Anonymous access is now rejected for user-owned resumes.

    Resumes with no owner (user_id IS NULL) remain accessible to all; they
    are legacy rows created before auth was introduced.
    """
    if resume.user_id is None:
        return  # legacy resume with no owner — allow all callers
    if current_user is None:
        # Block unauthenticated access to user-owned resume data.
        raise HTTPException(
            status_code=401,
            detail="Authentication required to access this resume",
        )
    if resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
