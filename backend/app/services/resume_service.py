import io
import re
import asyncio
from datetime import datetime
from types import SimpleNamespace
import pdfplumber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.async_utils import run_blocking
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, Resume, ResumeSkill, Skill
from app.services.live_job_registry import get_job as registry_get_job, is_ephemeral_job_id
from app.services.live_resume_registry import (
    get_resume as registry_get_resume,
    is_ephemeral_resume_id,
    register_resume as registry_register_resume,
    set_skill_names as registry_set_skill_names,
)
from app.services.skill_normalizer import normalize_skill_list
from app.services.skill_service import (
    extract_skills_from_text,
    filter_technical_skills_only,
    get_or_create_skills,
)

# When KeyBERT / extraction returns nothing, persist a minimal safe set so gap analysis never stalls.
_DEFAULT_RESUME_SKILLS: frozenset[str] = frozenset({
    "communication",
    "problem solving",
    "python",
    "sql",
    "git",
})
from app.services.llm_service import (
    generate as llm_generate,
    is_llm_enabled,
    resume_summary as llm_resume_summary,
)

logger = get_logger(__name__)


_EXP_YEARS_PATTERN = re.compile(
    r"""
    (?:
        (?:over|more\s+than|at\s+least)\s+   # modifiers like 'over 4 years'
    )?
    (?<![\d\-–])(?P<num>\d+)
    \s*
    \+?
    \s*
    (?:years?|yrs?|yoe)\b                   # explicit experience unit required
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EXP_RANGE_PATTERN = re.compile(
    r"""
    (?P<lo>\d+)
    \s*[-–]\s*
    (?P<hi>\d+)
    \s*
    (?:years?|yrs?|yoe)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EXP_YEAR_SPAN_PATTERN = re.compile(
    r"\b(?P<start>(?:19|20)\d{2})\s*(?:-|–|to)\s*(?P<end>(?:19|20)\d{2}|present)\b",
    re.IGNORECASE,
)


def extract_experience_years(text: str) -> float:
    """
    Best-effort years-of-experience extractor from resume text.
    Returns a non-negative float; default 0.0 when no signal is found.
    """
    if not text or not isinstance(text, str):
        return 0.0
    t = text.lower()
    # Prefer explicit forms like "2 years", "3+ yrs", "over 4 years".
    m = _EXP_YEARS_PATTERN.search(t)
    if m:
        try:
            num = int(m.group("num"))
            if num >= 0:
                return float(num)
        except (TypeError, ValueError):
            return 0.0
    # Fallback: explicit experience ranges like "2-4 years" → conservative mid-point.
    m_range = _EXP_RANGE_PATTERN.search(t)
    if m_range:
        try:
            lo = int(m_range.group("lo"))
            hi = int(m_range.group("hi"))
            if lo >= 0 and hi >= lo:
                return float((lo + hi) / 2.0)
        except (TypeError, ValueError):
            pass
    # Final fallback: year spans such as "2019-2023", "2020 – present", "2018 to 2022".
    m_years = _EXP_YEAR_SPAN_PATTERN.search(t)
    if m_years:
        now_year = datetime.now().year
        try:
            start = int(m_years.group("start"))
            end_raw = (m_years.group("end") or "").lower()
            end = now_year if end_raw == "present" else int(end_raw)
            if start > now_year or end > now_year:
                return 0.0
            if end < start:
                return 0.0
            return float(max(0, end - start))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def suggest_roles_from_resume(resume_text: str, *, max_roles: int = 5) -> list[str]:
    """
    Heuristic role suggestions from resume text (no ML deps).
    Returns 3–5 display titles, highest signal first.
    """
    t = (resume_text or "").lower()
    if not t.strip():
        return []

    score: dict[str, int] = {
        "AI Engineer": 0,
        "Machine Learning Engineer": 0,
        "Data Engineer": 0,
        "Backend Engineer": 0,
        "Frontend Engineer": 0,
        "DevOps Engineer": 0,
        "Data Scientist": 0,
        "Data Analyst": 0,
        "Software Engineer": 0,
        "Cloud Engineer": 0,
    }

    # Depth before treating resume as MLE-level ML (courses/NLP keywords alone are weak).
    strong_ml_signals = [
        "tensorflow",
        "pytorch",
        "model deployment",
        "production",
        "mlops",
        "training pipelines",
        "feature engineering",
        "model evaluation",
    ]
    has_strong_ml = any(s in t for s in strong_ml_signals)

    ai_signals = [
        "llm", "langchain", "rag", "agent", "openai", "transformer", "genai",
    ]
    # Weak ML surface (libs/courses) — penalized when no strong_ml_signals.
    ml_weak_signals = ["sklearn", "xgboost", "model training", "supervised learning"]
    data_signals = ["airflow", "spark", "etl", "data pipeline", "snowflake", "databricks", "sql", "kafka"]
    backend_signals = ["backend", "rest api", "graphql", "microservice", "django", "flask", "spring", "node"]
    frontend_signals = ["frontend", "react", "vue", "angular", "typescript", "css", "html", "next.js"]
    devops_signals = ["devops", "sre", "docker", "kubernetes", "terraform", "jenkins", "ci/cd", "prometheus", "grafana"]
    backend_boost_signals = ["flask", "rest api", "sql", "backend", "python"]

    if any(s in t for s in ai_signals):
        score["AI Engineer"] += 5
    if any(s in t for s in ml_weak_signals):
        score["Machine Learning Engineer"] += 3
    if "machine learning" in t or re.search(r"\bml\b", t):
        score["Machine Learning Engineer"] += 2
    if has_strong_ml:
        score["Machine Learning Engineer"] += 3
    if any(s in t for s in data_signals):
        score["Data Engineer"] += 2
    if any(s in t for s in backend_signals):
        score["Backend Engineer"] += 2
    if any(s in t for s in backend_boost_signals):
        score["Backend Engineer"] += 3
    if any(s in t for s in frontend_signals):
        score["Frontend Engineer"] += 2
    if any(s in t for s in devops_signals):
        score["DevOps Engineer"] += 2
    if "data scientist" in t or "data science" in t:
        score["Data Scientist"] += 3
    if "data analyst" in t:
        score["Data Analyst"] += 3
    elif "analytics" in t or "business intelligence" in t:
        score["Data Analyst"] += 2
    if "software engineer" in t or "software developer" in t:
        score["Software Engineer"] += 3
    elif "developer" in t:
        score["Software Engineer"] += 2
    elif "python" in t:
        score["Software Engineer"] += 1
    if "aws" in t or "gcp" in t or "azure" in t:
        score["Cloud Engineer"] += 1

    mle = score["Machine Learning Engineer"]
    if mle > 0 and not has_strong_ml:
        score["Machine Learning Engineer"] = max(0, int(round(mle * 0.5)))

    if not has_strong_ml:
        score["Machine Learning Engineer"] = max(
            0,
            min(
                score["Machine Learning Engineer"],
                score["Backend Engineer"] - 1,
            ),
        )

    ranked = [
        role
        for role, pts in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
        if pts > 0
    ]
    if not ranked:
        ranked = ["Software Engineer"]
    return ranked[:max_roles]


async def suggest_roles_hybrid(resume_text: str, *, max_roles: int = 5) -> list[str]:
    """
    Rule-based role suggestions with optional LLM reranking.
    If LLM is unavailable, times out, or returns invalid output, returns
    deterministic rule-based ordering.
    """
    roles = suggest_roles_from_resume(resume_text, max_roles=max_roles)
    if not roles:
        return []
    if not is_llm_enabled():
        return roles

    prompt = (
        "Given this resume, rank these roles by relevance:\n"
        f"{roles}\n\n"
        "Resume:\n"
        f"{(resume_text or '')[:4000]}\n\n"
        "Return ranked list only."
    )
    try:
        raw = await asyncio.wait_for(llm_generate(prompt, max_retries=0), timeout=4.0)
    except Exception as exc:
        logger.debug("role_rerank llm timeout/failure: %s", exc)
        return roles
    if not raw:
        return roles

    allowed = {r.strip().lower(): r for r in roles}
    ranked: list[str] = []
    seen: set[str] = set()
    # Accept simple list formats: newline, comma, numbered bullets.
    chunks = re.split(r"[\n,]", raw)
    for c in chunks:
        item = re.sub(r"^\s*[\-\*\d\.\)]\s*", "", c).strip()
        if not item:
            continue
        key = item.lower()
        if key in allowed and key not in seen:
            seen.add(key)
            ranked.append(allowed[key])

    if not ranked:
        return roles
    # Keep validated ranked order and append any remaining original roles.
    for r in roles:
        k = r.lower()
        if k not in seen:
            ranked.append(r)
    return ranked[:max_roles]


def extract_text_from_pdf(file_content: bytes) -> str:
    """Synchronous PDF text extraction — must be called via run_blocking()."""
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def _namespace_from_registry(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        filename=row["filename"],
        candidate_name=row.get("candidate_name"),
        raw_text=row.get("raw_text"),
        ai_summary=row.get("ai_summary"),
        user_id=row.get("user_id"),
        created_at=row.get("created_at"),
    )


async def resume_exists(session: AsyncSession, resume_id: int) -> bool:
    if is_ephemeral_resume_id(resume_id):
        return registry_get_resume(resume_id) is not None
    return (await session.get(Resume, resume_id)) is not None


async def job_exists(session: AsyncSession, job_id: int) -> bool:
    if is_ephemeral_job_id(job_id):
        return registry_get_job(job_id) is not None
    return (await session.get(Job, job_id)) is not None


class ResumeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_resume(
        self,
        filename: str,
        file_content: bytes,
        candidate_name: str | None = None,
        *,
        user_id: int | None = None,
    ) -> Resume | SimpleNamespace:
        # pdfplumber is CPU/IO-bound; run in executor so the event loop stays
        # responsive during concurrent uploads.
        raw_text = await run_blocking(extract_text_from_pdf, file_content)
        skill_names = await run_blocking(extract_skills_from_text, raw_text or "")
        if not skill_names and (raw_text or "").strip():
            skill_names = set(_DEFAULT_RESUME_SKILLS)
        if isinstance(skill_names, set):
            skill_list = normalize_skill_list([str(x) for x in skill_names])
        else:
            skill_list = normalize_skill_list([str(x) for x in (skill_names or [])])

        if not get_settings().persist_resumes:
            ai_summary = None
            if is_llm_enabled() and (raw_text or "").strip():
                try:
                    summary = await llm_resume_summary(raw_text or "")
                    if summary:
                        ai_summary = summary
                except Exception:
                    pass
            rid = registry_register_resume(
                filename=filename,
                raw_text=raw_text or None,
                candidate_name=candidate_name,
                skill_names=skill_list,
                user_id=user_id,
                ai_summary=ai_summary,
            )
            row = registry_get_resume(rid)
            assert row is not None
            return _namespace_from_registry(row)

        resume = Resume(
            filename=filename,
            candidate_name=candidate_name,
            raw_text=raw_text or None,
            user_id=user_id,
        )
        self.session.add(resume)
        await self.session.flush()
        if skill_list:
            skills = await get_or_create_skills(self.session, skill_list)
            for skill in skills:
                self.session.add(ResumeSkill(resume_id=resume.id, skill_id=skill.id))
            await self.session.flush()
        if is_llm_enabled() and (raw_text or "").strip():
            try:
                summary = await llm_resume_summary(raw_text or "")
                if summary:
                    resume.ai_summary = summary
                    await self.session.flush()
            except Exception:
                pass  # Don't fail upload if LLM is unavailable; resume is still saved
        return resume

    async def get_resume(self, resume_id: int) -> Resume | SimpleNamespace | None:
        if is_ephemeral_resume_id(resume_id):
            row = registry_get_resume(resume_id)
            return _namespace_from_registry(row) if row else None
        stmt = select(Resume).where(Resume.id == resume_id)
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def get_resume_with_skills(
        self, resume_id: int,
    ) -> tuple[Resume | SimpleNamespace | None, list[str]]:
        if is_ephemeral_resume_id(resume_id):
            row = registry_get_resume(resume_id)
            if not row:
                return None, []
            names = filter_technical_skills_only(list(row.get("skill_names") or []))
            return _namespace_from_registry(row), names
        resume = await self.get_resume(resume_id)
        if not resume:
            return None, []
        stmt = select(Skill.name).join(ResumeSkill, ResumeSkill.skill_id == Skill.id).where(
            ResumeSkill.resume_id == resume_id
        )
        names = filter_technical_skills_only(
            list((await self.session.execute(stmt)).scalars().all())
        )
        return resume, names

    async def ensure_resume_skills(self, resume_id: int) -> bool:
        """If resume has raw_text but no skills, extract and save. Returns True if resume exists."""
        resume, names = await self.get_resume_with_skills(resume_id)
        if not resume:
            return False
        if names:
            return True
        raw = resume.raw_text or ""
        if not raw.strip():
            return True
        skill_names = await run_blocking(extract_skills_from_text, raw)
        if not skill_names and raw.strip():
            skill_names = set(_DEFAULT_RESUME_SKILLS)
        if isinstance(skill_names, set):
            skill_list = normalize_skill_list([str(x) for x in skill_names])
        else:
            skill_list = normalize_skill_list([str(x) for x in (skill_names or [])])
        if not skill_list:
            return True
        if is_ephemeral_resume_id(resume_id):
            registry_set_skill_names(resume_id, skill_list)
            return True
        skills = await get_or_create_skills(self.session, skill_list)
        for skill in skills:
            self.session.add(ResumeSkill(resume_id=resume.id, skill_id=skill.id))
        await self.session.flush()
        return True
