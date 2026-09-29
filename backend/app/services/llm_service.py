"""
Local LLM service (Ollama-compatible). Optional: if LLM_BASE_URL is not set, all functions return None.
Supports structured JSON output for match and gap advice (bullet improvements, rewritten bullets, metrics).
"""
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.match import GapAdviceStructuredOut, MatchAdviceStructuredOut, RewrittenBulletOut
from app.services.skill_service import is_high_demand_row_acceptable

logger = get_logger(__name__)

# JSON schema instructions for structured output
MATCH_ADVICE_JSON_SCHEMA = """{
  "fit_level": "strong" or "moderate" or "needs_work",
  "fit_reason": "2-3 sentences: WHY they fit or do not fit this specific job (tie to job description + resume)",
  "priority": ["ordered action or skill focus", "..."],
  "highlight": "one line what to emphasize from the resume for this job",
  "next_step": "single most important next action this week",
  "highlights": ["extra emphasis bullets for interviews or resume lead"],
  "bullet_improvements": ["how to strengthen a resume bullet for THIS job", "..."],
  "rewritten_bullets": [{"original": "one resume bullet", "rewritten": "same bullet rewritten for this job"}],
  "measurable_metrics": ["quantified outcomes they could credibly add, tied to JD themes", "..."],
  "improve_skills": ["missing skills that would move the needle for this posting", "..."]
}"""

GAP_ADVICE_JSON_SCHEMA = """{
  "prioritize": ["One tight line each: skill or theme — why it matters (optionally add demand % in parentheses). Max ~140 chars. Plain text only — no ** markdown, no '1.' numbering inside the string.",
  "highlight_how": "2–3 sentences max: confident interview framing for their strongest market overlap. No bullet list.",
  "next_step": "One imperative sentence — the single best move in the next few days.",
  "project_ideas": ["Short: catchy title — one line (stack + proof of skill)", "..."],
  "learning_path": ["3–6 steps: each starts with a verb; ≤100 chars; foundations → practice → proof", "..."],
  "bullet_improvements": ["Concrete resume line upgrades; avoid generic advice", "..."],
  "measurable_metrics": ["Quantified outcomes they can credibly claim; ≤15 words each", "..."]
}"""

# Built-in prompts (used when llm_prompts_path is not set or key missing)
DEFAULT_PROMPTS = {
    "resume_summary": (
        "Using ONLY the resume text below, write exactly 2-3 sentences in this format:\n\n"
        "Strengths: [one sentence on main technical skills and experience]\n"
        "Role fit: [one sentence on best job titles or areas]\n\n"
        "Use only facts from the text. No greetings or sign-offs.\n\n"
        "Resume text:\n---\n{resume_text}\n---\n\nOutput:"
    ),
    "gap_advice": (
        "You are a sharp career coach. Be scannable: short lines, strong verbs, no essays.\n"
        "Target role: {target_role}\n"
        "Experience level: {experience_level} ({experience_interpretation})\n\n"
        "Your skills (from resume): {your_skills}\n"
        "Top matched market skills (strengths to lean on): {top_matched_skills}\n"
        "Matched with market: {matched_skills}\n"
        "Missing (market asks; you lack): {missing_skills}\n"
        "High-demand missing (name + typical demand %): {high_demand_missing}\n\n"
        "Rules: Weight BOTH posting demand and relevance to {target_role}. Name real tools and project shapes. "
        "No markdown headings like **Prioritized skills**. No numbered walls of text—use tight bullets.\n"
        "Use skill names from the lists. No greetings or sign-offs.\n\n"
        "Prioritize (2–4 lines, one skill hook per line):\n"
        "Highlight (2–3 sentences — interview pitch for their strengths):\n"
        "Next step (one imperative sentence):\n"
        "Project ideas (1–2 lines each):\n\n"
        "Candidate resume (excerpt):\n---\n{resume_text}\n---\n\n"
        "Job market sample:\n{market_job_descriptions}\n\n"
        "Output:"
    ),
    "gap_advice_json": (
        "You are a sharp, encouraging career coach. Respond with ONLY a valid JSON object (no markdown fences, no text outside JSON).\n\n"
        "Target role: {target_role}\n"
        "Experience level: {experience_level} — {experience_interpretation}\n\n"
        "Your skills (from resume): {your_skills}\n"
        "Top matched market skills: {top_matched_skills}\n"
        "Matched with market: {matched_skills}\n"
        "Missing: {missing_skills}\n"
        "High-demand missing (skill + demand context): {high_demand_missing}\n\n"
        "Voice & format (critical):\n"
        "- Write like a coach who respects their time: energetic, direct, scannable. No academic tone.\n"
        "- prioritize: 3–5 items. Each ONE line, ≤140 characters. Lead with the skill name, em dash or colon, one crisp hook. "
        "Optional demand % in parentheses. Do NOT paste essay paragraphs, numbered sub-lists, or **bold** markdown inside strings.\n"
        "- highlight_how: 2–3 sentences total — how they should talk about their edge in interviews.\n"
        "- next_step: one imperative sentence (specific tool, artifact, or milestone).\n"
        "- learning_path: 3–6 steps; each step starts with a verb; short enough to skim in 10 seconds.\n"
        "- project_ideas: 2 ideas max; each is 'Title — one line scope' (what to build + stack).\n"
        "- Avoid hedging filler ('Although not explicitly mentioned', 'It can be inferred'). If a skill is missing, say so in one clause.\n"
        "- Tie claims to the resume excerpt and job market sample when you can.\n\n"
        "Schema:\n" + GAP_ADVICE_JSON_SCHEMA.replace("{", "{{").replace("}", "}}") + "\n\n"
        "Candidate resume (excerpt):\n---\n{resume_text}\n---\n\n"
        "Job market sample:\n{market_job_descriptions}\n\n"
        "Respond with only the JSON object:"
    ),
    "match_advice": (
        "You are advising a candidate for a specific job. Role cluster: {role_cluster} (use examples appropriate to this family).\n"
        "Use the resume excerpt and job listing. Write 2-4 lines:\n\n"
        "Fit: [strong / moderate / needs work] — [WHY: tie claims to the job description and their resume]\n"
        "Highlight: [what to emphasize in interviews / resume lead]\n"
        "Improve: [missing skills + one measurable metric idea from the JD]\n\n"
        "Use the exact skill names given. No greetings or sign-offs.\n\n"
        "Candidate resume (excerpt):\n---\n{resume_text}\n---\n\n"
        "Job title: {job_title}\n"
        "Job description:\n---\n{job_description}\n---\n\n"
        "Scores: {match_score}% overall | semantic {semantic}% | overlap {skill_overlap}% | keyword {keyword}%\n"
        "Matched: {matched_skills} | Missing: {missing_skills}\n\n"
        "Output:"
    ),
    "match_advice_json": (
        "You are a senior career coach. The candidate is applying to one specific role. "
        "Respond with ONLY a valid JSON object (no markdown, no code fences).\n\n"
        "Explain clearly WHY they are a strong, moderate, or weak fit—reference both the job description and resume facts. "
        "Give resume bullet rewrites and metrics suggestions that map to phrases or themes in the job description. "
        "Role cluster (for tone): {role_cluster} — tailor examples to this family (ML vs Data vs Backend vs General).\n\n"
        "Schema:\n" + MATCH_ADVICE_JSON_SCHEMA.replace("{", "{{").replace("}", "}}") + "\n\n"
        "Candidate resume (excerpt):\n---\n{resume_text}\n---\n\n"
        "Job title: {job_title}\n"
        "Role cluster: {role_cluster}\n"
        "Job description:\n---\n{job_description}\n---\n\n"
        "Scores (0–100): overall {match_score}% | semantic {semantic}% | skill overlap {skill_overlap}% | keyword {keyword}%\n"
        "Matched skills: {matched_skills} | Missing: {missing_skills}\n\n"
        "Respond with only the JSON object:"
    ),
    "verify_skills": (
        "You are given phrases extracted from a resume. Return a JSON object with a single key \"skills\" and a list of skill names.\n\n"
        "Rules:\n"
        "1. Return ONLY real technical/professional skills: languages (Python, Java, SQL), frameworks (TensorFlow, PyTorch), tools (Git, Docker, Airflow), platforms (AWS, GCP, Azure), and similar.\n"
        "2. SPLIT combined phrases into separate skills. Example: 'langgraph airflow' -> [\"LangGraph\", \"Airflow\"]. 'gcp kubernetes' -> [\"GCP\", \"Kubernetes\"]. 'mlops grafana prometheus' -> [\"MLOps\", \"Grafana\", \"Prometheus\"].\n"
        "3. Use standard names: Python not python, AWS not aws, TensorFlow not tensorflow. One skill per list item (e.g. 'REST API' not 'REST APIs').\n"
        "4. EXCLUDE: emails, phone numbers, university names, locations (e.g. noida), sentence fragments (e.g. 'orchestration team tech', 'contributed azure openai'), job titles, 'key projects', generic words.\n"
        "5. If a phrase is clearly two or more skills stuck together (e.g. 'snowflake feature engineering'), split into [\"Snowflake\", \"Feature Engineering\"].\n"
        "6. Do not add skills that do not appear in or are not clearly implied by the list below.\n\n"
        "Phrases (one per line):\n{candidate_phrases}\n\n"
        "Respond with ONLY this JSON object, no other text: {{\"skills\": [\"Skill1\", \"Skill2\", ...]}}"
    ),
    "verify_high_demand_skills": (
        "You filter candidate phrases for the \"Top skills to learn\" UI. Only items verified as "
        "learnable TECHNICAL skills may remain.\n"
        "Target role context: {target_role}\n\n"
        "Each line is: index<TAB>skill_name<TAB>demand_pct\n"
        "{numbered_rows}\n\n"
        "Task: return ONLY valid JSON (no markdown) with shape: {{\"keep\": [int, ...]}}\n"
        "- \"keep\" lists 0-based row indices to KEEP (at most 12), in ascending order.\n"
        "- KEEP ONLY concrete technical / professional skills someone can study or certify: "
        "programming languages, frameworks, libraries, runtimes, clouds, databases, data tools, "
        "ML/AI stacks, DevOps/MLOps tools, protocols, query engines (e.g. Python, Rust, TypeScript, "
        "React, FastAPI, Spark, Airflow, AWS, GCP, BigQuery, PostgreSQL, Kubernetes, Docker, "
        "TensorFlow, PyTorch, LangChain).\n"
        "- DROP soft skills and traits (communication, leadership, teamwork, problem-solving, agile mindset).\n"
        "- DROP industries, domains, job titles, seniority, company names, recruiter text, HR/diversity lines.\n"
        "- DROP role titles even if they sound technical: \"Cloud Architect\", \"Product Manager\", "
        "\"Senior AI Engineer\", \"Data Scientist\", \"AI/ML Specialists\", \"Software Engineer\" — these are jobs, "
        "not skills to study.\n"
        "- DROP sentence fragments, incomplete parentheses, mashups of multiple unrelated tokens, marketing prose.\n"
        "- ALWAYS DROP: advertisers, LinkedIn, agencies, entry level, experimentation, industries software, "
        "driven insights, marketing or ad-tech business words, company-name-like tokens.\n"
        "- DROP: great fit / good fit / strong match, hackajob, hackerrank, leetcode, recruiter platforms.\n"
        "- DROP HR fragments: \"ability drive\", \"ability to drive\", \"advanced sql experience\" "
        "(not a skill name).\n"
        "- If every row is not a technical skill, return {{\"keep\": []}}.\n\n"
        "Respond with only the JSON object:"
    ),
}


from functools import lru_cache


@lru_cache(maxsize=1)
def _load_prompts() -> dict[str, str]:
    """
    Load prompt templates once and cache indefinitely.
    Previously this read the JSON file from disk on every LLM call (blocking
    the event loop via open/json.load in an async context). lru_cache ensures
    the file is parsed at most once per process lifetime.
    Settings are frozen at startup so the cache is always valid.
    """
    settings = get_settings()
    if settings.llm_prompts_path:
        path = Path(settings.llm_prompts_path)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {**DEFAULT_PROMPTS, **data}
            except Exception as e:
                logger.warning("Failed to load prompts from %s: %s", path, e)
    return dict(DEFAULT_PROMPTS)


def _get_prompt(name: str, **kwargs: str) -> str:
    prompts = _load_prompts()
    template = prompts.get(name) or DEFAULT_PROMPTS.get(name) or ""
    return template.format(**kwargs)


def is_llm_enabled() -> bool:
    settings = get_settings()
    return bool(settings.llm_base_url and settings.llm_base_url.strip())


async def _generate_once(prompt: str) -> str | None:
    """Single attempt to call local LLM. Raises on network/HTTP errors."""
    settings = get_settings()
    url = (settings.llm_base_url or "").rstrip("/") + "/api/generate"
    payload = {
        "model": settings.llm_model,
        "prompt": prompt,
        "stream": False,
        "format": "json" if prompt.endswith("Respond with only the JSON object:") else "",
    }
    tout = httpx.Timeout(
        settings.llm_timeout_seconds,
        connect=min(10.0, float(settings.llm_timeout_seconds)),
    )
    async with httpx.AsyncClient(timeout=tout) as client:
        t0 = time.perf_counter()
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        logger.info(
            "llm_latency_ms=%.1f model=%s prompt_chars=%d",
            (time.perf_counter() - t0) * 1000,
            settings.llm_model,
            len(prompt),
        )
        data = resp.json()
        text = data.get("response") or ""
        return _strip_signoffs(text.strip()) or None


async def generate(prompt: str, max_retries: int = 2) -> str | None:
    """
    Call local LLM with simple exponential-backoff retry (no extra dependency).
    Returns generated text or None if disabled or all attempts fail.
    """
    if not is_llm_enabled():
        return None
    import asyncio
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await _generate_once(prompt)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s
                logger.debug("LLM attempt %d failed (%s), retrying in %ds", attempt + 1, e, wait)
                await asyncio.sleep(wait)
    logger.warning(
        "LLM generate failed after %d attempts: %r",
        max_retries + 1,
        last_exc,
    )
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response (handles markdown code blocks)."""
    if not text or not text.strip():
        return None
    text = text.strip()
    # Try markdown code block first
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    # Find first { ... } if there's extra text
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _strip_signoffs(text: str) -> str:
    """Remove common LLM sign-off phrases from the end of the response."""
    if not text:
        return text
    lower = text.lower()
    signoffs = (
        "please let me know if you need",
        "let me know if you need",
        "feel free to reach out",
        "if you have any questions",
        "i'd be happy to help",
        "happy to help",
        "any other assistance",
        "anything else",
    )
    for phrase in signoffs:
        idx = lower.rfind(phrase)
        if idx != -1:
            # Cut from the start of that sentence (go back to last period or newline)
            before = text[:idx].rstrip()
            last_br = max(before.rfind("."), before.rfind("\n"))
            if last_br >= 0:
                text = before[: last_br + 1].strip()
            else:
                text = before
            return _strip_signoffs(text)
    return text


async def resume_summary(resume_text: str) -> str | None:
    """Generate a short resume summary. Truncate long text to avoid token limits."""
    if not resume_text or not resume_text.strip():
        return None
    # Keep first ~3000 chars to stay within context
    text = (resume_text.strip())[:3000]
    prompt = _get_prompt("resume_summary", resume_text=text)
    return await generate(prompt)


async def verify_skills_with_llm(candidate_phrases: list[str]) -> list[str]:
    """
    Send candidate phrases (e.g. from KeyBERT) to the local LLM; return only those the LLM
    considers real professional/technical skills. Used to clean 'Your skills' on the resume.
    If LLM is disabled or fails, returns the original list unchanged.
    """
    if not candidate_phrases:
        return []
    if not is_llm_enabled():
        return list(candidate_phrases)
    # Truncate to avoid token limits
    phrases = list(candidate_phrases)[:80]
    lines = "\n".join(f"- {p}" for p in phrases)
    prompt = _get_prompt("verify_skills", candidate_phrases=lines)
    raw = await generate(prompt)
    if not raw:
        return list(candidate_phrases)
    obj = _extract_json(raw)
    if not obj:
        return list(candidate_phrases)
    skills = obj.get("skills")
    if not isinstance(skills, list):
        return list(candidate_phrases)
    result = [str(s).strip() for s in skills if s and str(s).strip()]
    return result if result else list(candidate_phrases)


async def verify_high_demand_missing_skills_llm(
    rows: list[dict],
    target_role: str,
) -> list[dict] | None:
    """
    Local Ollama-compatible LLM picks which rows are learnable technical skills for \"Top skills to learn\"
    (indices only; preserves demand %). Returns None if LLM is disabled or the call/parse fails
    (caller should fall back to heuristics).
    """
    if not rows:
        return []
    if not is_llm_enabled():
        return None
    capped = list(rows)[:45]
    lines: list[str] = []
    for i, r in enumerate(capped):
        name = str(r.get("skill_name") or "").strip() or "?"
        try:
            pct = float(r.get("demand_percentage") or 0.0)
        except (TypeError, ValueError):
            pct = 0.0
        lines.append(f"{i}\t{name}\t{pct:.1f}%")
    numbered_rows = "\n".join(lines)
    prompt = _get_prompt(
        "verify_high_demand_skills",
        target_role=(target_role or "Software / tech").strip()[:160],
        numbered_rows=numbered_rows,
    )
    raw = await generate(prompt, max_retries=1)
    if not raw:
        return None
    obj = _extract_json(raw)
    if not obj:
        return None
    keep = obj.get("keep")
    if not isinstance(keep, list):
        return None
    out: list[dict] = []
    seen: set[int] = set()
    for x in keep:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i < 0 or i >= len(capped) or i in seen:
            continue
        row = dict(capped[i])
        sn = str(row.get("skill_name") or "").strip()
        if not is_high_demand_row_acceptable(sn):
            continue
        seen.add(i)
        out.append(row)
        if len(out) >= 12:
            break
    return out


def _fmt_skills(items: list) -> str:
    if not items:
        return "None"
    if isinstance(items[0], dict):
        return ", ".join((x.get("skill_name") or x.get("name") or str(x) for x in items[:20]))
    return ", ".join(str(s) for s in items[:20])


def _fmt_high_demand_with_pct(items: list) -> str:
    """Format SkillDemand-like dicts as 'skill (NN% of postings)'."""
    if not items:
        return "None"
    parts: list[str] = []
    for x in items[:15]:
        if isinstance(x, dict):
            name = x.get("skill_name") or x.get("name") or ""
            pct = x.get("demand_percentage")
            if name and pct is not None:
                parts.append(f"{name} (~{float(pct):.1f}% of postings)")
            elif name:
                parts.append(str(name))
        else:
            parts.append(str(x))
    return ", ".join(parts) if parts else "None"


def infer_role_cluster(job_title: str) -> str:
    """Coarse bucket for LLM tone: ML | Data | Backend | General."""
    t = (job_title or "").lower()
    if any(
        k in t
        for k in (
            "machine learning",
            "ml engineer",
            "ai engineer",
            "nlp",
            "llm",
            "deep learning",
            "computer vision",
            "research scientist",
            "applied scientist",
        )
    ):
        return "ML"
    if any(
        k in t
        for k in (
            "data engineer",
            "data scientist",
            "analytics engineer",
            "bi developer",
            "etl",
            "snowflake",
            "warehouse",
        )
    ):
        return "Data"
    if any(
        k in t
        for k in (
            "backend",
            "back-end",
            "api engineer",
            "full stack",
            "fullstack",
            "frontend",
            "front-end",
            "devops",
            "sre",
            "platform engineer",
            "software engineer",
            "java developer",
            "python developer",
        )
    ):
        return "Backend"
    return "General"


async def gap_advice(
    your_skills: list[str],
    matched_skills: list[str],
    missing_skills: list[str],
    high_demand_missing: list[str] | list[dict],
    market_job_descriptions: str = "",
    resume_text: str = "",
    *,
    target_role: str = "",
    experience_level: str = "unknown",
    experience_interpretation: str = "Not specified",
    top_matched_skills: list[str] | None = None,
) -> tuple[GapAdviceStructuredOut | None, str | None]:
    """Generate gap advice from one prompt: your skills, matched with market, missing. Returns (structured, fallback_text)."""
    # Truncate aggressively: 7B models have ~4K context; leave room for prompt template + JSON response
    resume_excerpt = " ".join((resume_text or "").strip().split()[:800])  # ~800 words
    top_m = top_matched_skills if top_matched_skills is not None else matched_skills
    hd_fmt = (
        _fmt_high_demand_with_pct(high_demand_missing)
        if high_demand_missing and isinstance(high_demand_missing[0], dict)
        else _fmt_skills(high_demand_missing[:10])
    )
    args = {
        "target_role": (target_role or "General tech / open search").strip()[:120],
        "experience_level": (experience_level or "unknown").strip()[:40],
        "experience_interpretation": (experience_interpretation or "Not specified").strip()[:120],
        "your_skills": ", ".join(your_skills[:20]) if your_skills else "None",
        "top_matched_skills": _fmt_skills(top_m[:12]),
        "matched_skills": _fmt_skills(matched_skills[:15]),
        "missing_skills": _fmt_skills(missing_skills[:12]),
        "high_demand_missing": hd_fmt,
        "market_job_descriptions": (market_job_descriptions.strip() or "No job listings sample available.")[:1000],
        "resume_text": resume_excerpt or "No resume text available.",
    }
    # Try structured JSON first
    prompts = _load_prompts()
    if "gap_advice_json" in prompts or "gap_advice_json" in DEFAULT_PROMPTS:
        prompt = _get_prompt("gap_advice_json", **args)
        # Single attempt: default retries × llm_timeout_seconds blocks gap HTTP for several minutes if Ollama hangs.
        raw = await generate(prompt, max_retries=0)
        if raw:
            obj = _extract_json(raw)
            if obj:
                try:
                    pri = list(obj.get("priority") or obj.get("prioritize") or [])
                    hl = (obj.get("highlight") or obj.get("highlight_how") or "").strip()
                    lp = list(obj.get("learning_path") or obj.get("learning_path_steps") or [])
                    proj = list(obj.get("project_ideas") or [])
                    structured = GapAdviceStructuredOut(
                        prioritize=pri,
                        priority=list(pri),
                        highlight_how=hl,
                        highlight=hl,
                        next_step=(obj.get("next_step") or "").strip(),
                        bullet_improvements=obj.get("bullet_improvements") or [],
                        measurable_metrics=obj.get("measurable_metrics") or [],
                        project_ideas=proj,
                        learning_path=lp,
                    )
                    fallback = _gap_advice_fallback_text(structured)
                    return (structured, fallback)
                except Exception as e:
                    logger.debug("Gap advice JSON validation failed: %s", e)
    # Fallback to plain-text prompt (single attempt — avoid stacking retries after JSON path).
    prompt = _get_prompt("gap_advice", **args)
    text = await generate(prompt, max_retries=0)
    return (None, text)


def _gap_advice_fallback_text(s: GapAdviceStructuredOut) -> str:
    """Build a short fallback summary from structured gap advice (plain text, scannable)."""
    lines: list[str] = []
    if s.prioritize:
        lines.append("Focus first:")
        lines.extend(f"• {p}" for p in s.prioritize[:6])
    if s.highlight_how:
        lines.append("")
        lines.append("Interview angle: " + s.highlight_how[:280] + ("…" if len(s.highlight_how) > 280 else ""))
    if s.next_step:
        lines.append("")
        lines.append("Do next: " + s.next_step)
    if s.project_ideas:
        lines.append("")
        lines.append("Build:")
        lines.extend(f"• {p}" for p in s.project_ideas[:3])
    if s.learning_path:
        lines.append("")
        lines.append("Roadmap:")
        lines.extend(f"{i}. {step}" for i, step in enumerate(s.learning_path[:6], start=1))
    return "\n".join(lines).strip() if lines else ""


async def match_advice(
    match_score: float,
    semantic: float,
    skill_overlap: float,
    keyword: float,
    matched_skills: list[str],
    missing_skills: list[str],
    job_title: str = "",
    job_description: str = "",
    resume_text: str = "",
    *,
    role_cluster: str | None = None,
) -> tuple[MatchAdviceStructuredOut | None, str | None]:
    """Generate match advice. Returns (structured, fallback_text). Tries JSON first for robustness."""
    resume_excerpt = " ".join((resume_text or "").strip().split()[:800])  # ~800 words
    desc = (job_description or "").strip()[:1000]
    cluster = (role_cluster or infer_role_cluster(job_title)).strip()
    args = {
        "match_score": f"{match_score:.0f}",
        "semantic": f"{semantic:.0f}",
        "skill_overlap": f"{skill_overlap:.0f}",
        "keyword": f"{keyword:.0f}",
        "matched_skills": ", ".join(matched_skills[:10]) if matched_skills else "None",
        "missing_skills": ", ".join(missing_skills[:10]) if missing_skills else "None",
        "job_title": (job_title or "Job").strip(),
        "job_description": desc or "No description available.",
        "resume_text": resume_excerpt or "No resume text available.",
        "role_cluster": cluster,
    }
    # Try structured JSON first
    prompts = _load_prompts()
    if "match_advice_json" in prompts or "match_advice_json" in DEFAULT_PROMPTS:
        prompt = _get_prompt("match_advice_json", **args)
        raw = await generate(prompt)
        if raw:
            obj = _extract_json(raw)
            if obj:
                try:
                    rewritten: list[RewrittenBulletOut] = []
                    for rb in obj.get("rewritten_bullets") or []:
                        if isinstance(rb, dict) and rb.get("original") and rb.get("rewritten"):
                            rewritten.append(RewrittenBulletOut(original=rb["original"], rewritten=rb["rewritten"]))
                    highlights = list(obj.get("highlights") or [])
                    improve_skills = list(obj.get("improve_skills") or [])
                    priority = list(obj.get("priority") or improve_skills[:8])
                    highlight = (obj.get("highlight") or "").strip()
                    if not highlight and highlights:
                        highlight = (highlights[0] or "").strip()
                    next_step = (obj.get("next_step") or "").strip()
                    bullet_improvements = list(obj.get("bullet_improvements") or [])
                    if not next_step and bullet_improvements:
                        next_step = (bullet_improvements[0] or "").strip()
                    structured = MatchAdviceStructuredOut(
                        fit_level=(obj.get("fit_level") or "").strip() or "moderate",
                        fit_reason=(obj.get("fit_reason") or "").strip(),
                        highlights=highlights,
                        bullet_improvements=bullet_improvements,
                        rewritten_bullets=rewritten,
                        measurable_metrics=obj.get("measurable_metrics") or [],
                        improve_skills=improve_skills,
                        priority=priority,
                        highlight=highlight,
                        next_step=next_step,
                    )
                    fallback = _match_advice_fallback_text(structured)
                    return (structured, fallback)
                except Exception as e:
                    logger.debug("Match advice JSON validation failed: %s", e)
    # Fallback to plain-text prompt
    prompt = _get_prompt("match_advice", **args)
    text = await generate(prompt)
    return (None, text)


def _match_advice_fallback_text(s: MatchAdviceStructuredOut) -> str:
    """Build a short fallback summary from structured match advice."""
    parts = []
    if s.fit_level and s.fit_reason:
        parts.append(f"Fit: {s.fit_level} — {s.fit_reason[:150]}")
    if s.highlights:
        parts.append("Highlight: " + "; ".join(s.highlights[:3]))
    if s.improve_skills:
        parts.append("Improve: " + ", ".join(s.improve_skills[:5]))
    return "\n".join(parts) if parts else ""
