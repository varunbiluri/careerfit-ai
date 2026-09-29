import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import numpy as np
from sqlalchemy import select, func, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, JobSkill, ResumeSkill, Skill
from app.services.live_resume_registry import get_resume as get_live_resume_row, is_ephemeral_resume_id
from app.services.normalization import expand_role_family, normalize_role

logger = get_logger(__name__)
DEFAULT_SKILLS_PATH = Path(__file__).resolve().parents[2] / "data" / "skills_dictionary.json"
ROLE_SUGGESTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "role_suggestions.json"

# Skills to never treat as valid (e.g. "R" from "R&D" / "recommendation" false positives)
BLOCKLISTED_SKILLS: frozenset[str] = frozenset({
    "r",
    # Job-board / marketing / prose fragments mis-extracted as skills (see gap UI noise)
    "advertisers",
    "advertising",
    "advertiser",
    "agencies",
    "agency",
    "linkedin",
    "indeed",
    "glassdoor",
    "construct",
    "experimentation",
    "recruiting",
    "hiring",
    "salary",
    "benefits",
    "employer",
    "full-time",
    "fulltime",
    "part-time",
    "parttime",
    # Job-tech platforms / boards mis-extracted as skills
    "hackajob",
    "hackerrank",
    "leetcode",
    "codility",
    "greenhouse",
    "workday",
    # HR prose: "ability to drive X" mis-keyphrased as two words (PDF Nov 2026)
    "ability drive",
    "preferred",
    "python/r",
    # JD / recruiter noise (Apr 2026 exports)
    "success",
})

# Multi-word or partial phrases from job descriptions (lowercase substring match)
_BLOCKLIST_SKILL_JUNK_PHRASES: tuple[str, ...] = (
    "agencies identified",
    "identified ai",
    "entry level",
    "industries software",
    "driven insights",
    "intersection machine",
    "million digital",
    "vehicle lifecycle",
    "diversity people",
    "ux data teams",
    "com role",
    "documentation ll",
    "developer engineer capco",
    "software engineer solera",
    "touchpoint vehicle",
    "stack software",
    "both sql",
    "orm frameworks",
    "sql server)",
    "node.js (backend)",
    # HR / marketing / sentence fragments (PDF exports Apr 2026)
    "great fit",
    "strong potential",
    "proficient python",
    "planning solutions publishers",
    "modeling analysis experience",
    "security recommendations",
    "audience engagement",
    "capturing audience",
    "agent simulations build",
    "solutions publishers",
    "ability to drive",
    "advertising performance group",
    "advanced sql experience",
    "data trusted ai",
    "collaborate cross",
    # JD prose mis-extracted as skills (backend resume + DS-heavy SERP; Nov 2026)
    "deployment core responsibilities",
    "experience aws sagemaker",
    "industries services consulting",
    "management role overview",
    "mumbai direct impact",
    "core responsibilities",
    "services consulting",
)

# Job sites / ads as whole words (avoid blocking "linking" etc.)
_BLOCKLIST_SKILL_JUNK_RE = re.compile(
    r"\b(linkedin|indeed|glassdoor|upwork|monster|ziprecruiter|hackajob|hackerrank|"
    r"leetcode|codility|greenhouse|workday|lever\.?co|advertisers?|agenc(?:y|ies))\b",
    re.I,
)

# Seniority / level descriptors that appear in JD text but are not skills.
# Catches: "seniority level", "agile seniority level", "senior level", "mid-level", etc.
_SENIORITY_DESCRIPTOR_RE = re.compile(
    r"\bseniority\b|"
    r"\b(mid[- ]?level|entry[- ]?level|senior[- ]?level|junior[- ]?level|"
    r"associate[- ]?level|principal[- ]?level|lead[- ]?level)\b",
    re.I,
)

# Culture, personality, and workplace-vibe words that are never technical skills.
_CULTURE_PERSONALITY_WORDS: frozenset[str] = frozenset({
    "camaraderie", "fellowship", "belonging", "inclusive", "inclusivity",
    "diversity", "culture", "workplace", "grit", "passion", "passionate",
    "driven", "ambitious", "ambition", "dynamic", "synergy", "impactful",
    "exceptional", "outstanding", "talented", "gifted", "visionary",
    "transformative", "champion", "guru", "ninja", "rockstar", "wizard",
    "mindset", "entrepreneurial", "entrepreneur", "empowerment", "engagement",
    "enthusiasm", "morale", "wellbeing", "well-being", "belonging",
})

# Words that — when found as a whole word inside a multi-word phrase — indicate the
# phrase is a JD sentence fragment, not a skill name.
# Checked word-by-word so "machine learning" is not caught by "learning".
_FRAGMENT_DISQUALIFIER_WORDS: frozenset[str] = frozenset({
    # JD stop-words / action descriptors
    "stay", "understanding", "opportunities", "opportunity",
    "responsibilities", "responsibility", "requirements", "requirement",
    "productionalization", "roadmaps", "deliverables", "initiatives",
    "aligned", "oriented", "focused",
})

# Single-word industry sector nouns that describe a domain but are not themselves
# learnable technical skills (e.g. "insurance" is not something you learn like Python).
# Only applied to single-token inputs.
_INDUSTRY_NOUNS_NOT_SKILLS: frozenset[str] = frozenset({
    "insurance", "retail", "banking", "healthcare", "finance",
    "automotive", "pharmaceutical", "telecommunications",
    "manufacturing", "hospitality", "logistics", "procurement",
    "aviation", "agriculture", "reinsurance", "underwriting",
    "opportunities", "requirements", "responsibilities",
})

# Prose that is never a skill name (job ad filler, recruiter copy)
_SKILL_HR_FLUFF_RE = re.compile(
    r"\b(great|good|strong)\s+(fit|match)\b|"
    r"\bproficient\s+(python|java|javascript|typescript|sql|react|node)\b|"
    r"\b(modeling|planning)\s+analysis\s+experience\b|"
    r"\bsecurity\s+recommendations\b|"
    r"\b(planning|solutions)\s+publishers\b|"
    r"\bability\s+(to\s+)?drive\b|"
    r"\badvanced\s+sql\s+experience\b|"
    r"\badvertising\s+performance\s+group\b|"
    r"\bdeployment\s+core\s+responsibilities\b|"
    r"\bexperience\s+aws\s+sagemaker\b|"
    r"\bindustries\s+services\s+consulting\b|"
    r"\bmanagement\s+role\s+overview\b|"
    r"\bmumbai\s+direct\s+impact\b|"
    r"\bcore\s+responsibilities\b|"
    r"\bpython/r\b",
    re.I,
)


def _normalize_phrase_soft(s: str) -> str:
    """Lowercase, collapse whitespace, hyphen → space for soft-skill lookup."""
    return " ".join(str(s).strip().lower().split()).replace("-", " ")


# HR / behavioral competencies — excluded from gap/match skill lists (technical skills only in UI).
_SOFT_SKILL_PHRASES: frozenset[str] = frozenset({
    "accountability", "active listening", "adaptability", "adaptability and flexibility",
    "agility", "ambition", "analytical thinking", "attention to detail", "attitude",
    "authenticity", "awareness", "business acumen", "coaching", "collaboration",
    "communication", "communication skills", "compassion", "confidence", "conflict resolution",
    "creativity", "critical thinking", "cultural awareness", "curiosity", "customer focus",
    "customer service", "decision making", "decision-making", "deduction", "delegation",
    "dependability", "diplomacy", "discipline", "emotional intelligence", "empathy",
    "enthusiasm", "ethical judgment", "ethics", "facilitation", "flexibility",
    "friendliness", "good attitude", "growth mindset", "honesty", "humility",
    "influence", "initiative", "innovation", "innovative thinking", "inspiration",
    "integrity", "interpersonal skills", "leadership", "leadership skills", "listening",
    "loyalty", "maturity", "mentoring", "motivation", "multitasking", "negotiation",
    "negotiation skills", "networking", "open mindedness", "open-mindedness",
    "organization", "organizational skills", "patience", "people skills", "perseverance",
    "persistence", "persuasion", "positive attitude", "presentation skills", "prioritization",
    "problem solving", "problem-solving", "professionalism", "public speaking",
    "relationship building", "reliability", "resilience", "resourcefulness", "respect",
    "self awareness", "self discipline", "self motivation", "self-awareness",
    "self-discipline", "self-motivation", "stakeholder management", "storytelling",
    "stress management", "strong work ethic", "team building", "team player",
    "teamwork", "time management", "trainability", "verbal communication",
    "willingness to learn", "work ethic", "work life balance", "written communication",
    "collaborative", "dependable", "personable", "proactive", "self starter", "self-starter",
})


def is_soft_skill(name: str) -> bool:
    """True if this phrase is a behavioral / soft competency (not shown as a technical skill)."""
    if not name or not str(name).strip():
        return False
    p = _normalize_phrase_soft(name)
    if p in _SOFT_SKILL_PHRASES:
        return True
    return False


def filter_technical_skills_only(names: list[str]) -> list[str]:
    """Drop soft-skill entries; preserve order and dedupe."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if not n or not str(n).strip():
            continue
        if is_soft_skill(str(n)):
            continue
        k = str(n).strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(str(n).strip())
    return out

# Generic / non-skill tokens (lowercase)
_GENERIC_SKILL_WORDS: frozenset[str] = frozenset({
    "implementation", "system", "process", "experience", "learning", "summary",
    "level", "consultant", "development", "management", "delivery", "solutions",
    "technology", "technologies", "skills", "ability", "team", "project",
    "work", "working", "years", "strong", "hands", "on", "various", "learning",
    "multiple", "excellent", "good", "best", "practices", "knowledge",
    "understanding", "analysis", "design", "support", "services", "client",
})

# Hints that a phrase is tech / tool-like (substring match, lowercase)
_TECH_SKILL_HINT = re.compile(
    r"(machine learning|deep learning|reinforcement learning|computer vision|data science|"
    r"sql|api|aws|gcp|azure|docker|kubernetes|jenkins|git|linux|http|html|css|nlp|llm|"
    r"gpu|etl|ci/cd|ci\b|cd\b|sdk|rpc|rest|graphql|spark|kafka|airflow|pytorch|tensorflow|"
    r"keras|pandas|numpy|scikit|pytest|maven|gradle|redux|node|react|vue|angular|java|"
    r"python|scala|kotlin|swift|go\b|ruby|php|c\+\+|c#|\.js|js\b|ts\b|ml\b|ai\b|devops|"
    r"terraform|ansible|prometheus|grafana|mongodb|postgres|mysql|redis|snowflake|"
    r"databricks|kubernetes|sagemaker|bedrock|openai|hadoop|hive|dask|cuda|fpga|gpu)",
    re.I,
)

# Phrases that indicate sentence fragments from job descriptions (not real skill names)
_SKILL_SENTENCE_FRAGMENT_PATTERNS: tuple[str, ...] = (
    "help ", "join ", "or pods", "years of", "location ", "deliver ", "communicate ",
    "experience in", "hands on", "work with", "participate in", "proactively ",
    "leverage ", "demonstrate ", "facilitate ", "prepare ", "develop ", "build ",
    "maintain ", "ensure ", "provide ", "support ", "work closely", "actively ",
    "beyond core", "offering ", "compliance ", "lead knowledge", "clients achievements",
    "tips ", "recruiting ", "practitioner ", "functional ", "impacts ", "providing ",
    "powered ", "upgrading ", "reimagining ", "processing ", "helping ", "deploy ",
    "models agile", "engineering expertise", "prescribe actions", "insights services",
    "vertex ai).", "utilizing analytics", "leverage automation", "innovate enhance",
    "deploy operate", "integration structured", "containerization git", "pune chennai",
    "domains liaison", "methodologies for", "deep learning nlp", "agentic workflows versed",
    "etc. ai/cloud", "project requirements", "gen ai tools", "prepare technical",
    "helping transforming", "develop solutions", "du leadership", "contribute tracking",
    "engineering service", "ml deep learning", "experience following", "hands on experi",
    "build deploy", "clients achievements", "represents tangible", "learning schedule",
    "actively engage", "insights powered",     "summary position", "participate in pre-sales",
    "gemini aws", "client pursuits", "client teams to", "facilitate daily", "requirements work team",
    "technology operations", "leveraging our core", "reimagining engineering", "processing leverage",
    "implementation brainstorm", "capabilities ensuring", "design development", "maintaining date",
    "leverages cutting", "tips deloitte", "edge engineering", "lead knowledge sharing",
    "job function ", "stand resume", "knows about ", "help accelerate", "join ai ",
    "industries business", "or pods—", "tailored to each",
    "years of hands-on", "technology trends.",
    "enhance leadership", "boot experienced", "deliver projects", "ai based solutions",
    "mission critical", "open source llm", "microservices has", "microservices with react",
    "secure backend", "project understanding", "beyond core skills", "engineering-led advisory",
    "actively engage", "apis using java", "springboot", "compliance activities.",
    "modernize technology", "development of tools", "communicate issues", "cloud infrastructure insights",
    "innovative solutions team", "development operational", "reimagining engineering",
    "processing leverage", "hands on experi", "represents tangible", "learning schedule",
    "insights powered", "summary position", "gemini aws", "client teams to understand",
    "facilitate daily scrum", "requirements work team", "data engineers", "predict scenarios",
    "implementation brainstorm", "capabilities ensuring mature", "design development guides",
    "frameworks such as", "additional skill tensorflow", "forecasting automation",
)
_MAX_SKILL_NAME_LEN = 45
_MAX_SKILL_WORDS = 3

# Exact job-title phrases KeyBERT often emits as "skills" (not learnable tools).
_ROLE_TITLE_PHRASES_LOWER: frozenset[str] = frozenset({
    "cloud architects",
    "cloud architect",
    "product managers",
    "product manager",
    "senior ai engineer",
    "data engineers",
    "software engineers",
    "data scientists",
    "data scientist",
    "ai/ml specialists",
    "ai/ml specialist",
    "data trusted ai",
    "machine learning engineer",
    "machine learning engineers",
})

# e.g. "Senior AI Engineer", "Lead Data Scientist"
_SENIORITY_JOB_TITLE_RE = re.compile(
    r"\b(senior|junior|lead|principal|staff)\s+[\w./]+\s+(engineer|architect|developer|manager|scientist|analyst)\b",
    re.I,
)


def _looks_like_job_title_or_role(name: str) -> bool:
    """JD titles and role lines mis-tagged as technical skills."""
    low = " ".join(str(name).strip().lower().split())
    if low in _ROLE_TITLE_PHRASES_LOWER:
        return True
    if _SENIORITY_JOB_TITLE_RE.search(low):
        return True
    return False
# LinkedIn search: only short, tech-signal phrases (max 5 terms passed to URL in get_skills_for_scrape).
_MAX_SCRAPE_QUERY_WORDS = 3
_MAX_SCRAPE_KEYWORDS = 5
SCRAPE_QUERY_FALLBACK: list[str] = ["python", "machine learning", "data engineer"]
# Consecutive digits (e.g. job IDs or codes)
_SKILL_DIGIT_PATTERN = re.compile(r"\d{4,}")


def is_blocklisted_skill(name: str) -> bool:
    """True if this skill name should be excluded from extraction, storage, and UI (e.g. single 'R')."""
    if not name or not str(name).strip():
        return False
    low = str(name).strip().lower()
    if low in BLOCKLISTED_SKILLS:
        return True
    for phrase in _BLOCKLIST_SKILL_JUNK_PHRASES:
        if phrase in low:
            return True
    if _BLOCKLIST_SKILL_JUNK_RE.search(low):
        return True
    if _SKILL_HR_FLUFF_RE.search(low):
        return True
    return False


def is_tech_or_noun_like_skill(phrase: str) -> bool:
    """Keep noun-like or tech/tool-like phrases; drop generic prose."""
    if not phrase or not phrase.strip():
        return False
    s = phrase.strip().lower()
    words = [w for w in re.split(r"\s+", s) if w]
    if len(words) > _MAX_SKILL_WORDS:
        return False
    if _TECH_SKILL_HINT.search(s):
        return True
    if any(ch.isdigit() for ch in s) or "." in s or "+" in s or "#" in s:
        return True
    if len(words) == 1:
        w = words[0]
        if w in _GENERIC_SKILL_WORDS or len(w) < 2:
            return False
        return len(w) >= 3
    generic_only = all(w in _GENERIC_SKILL_WORDS for w in words)
    if generic_only:
        return False
    if len(words) >= 2:
        # If any word in the phrase is a known JD-fragment signal, reject immediately.
        if set(words) & _FRAGMENT_DISQUALIFIER_WORDS:
            return False
        non_g = [w for w in words if w not in _GENERIC_SKILL_WORDS]
        if not non_g:
            return False
        if _TECH_SKILL_HINT.search(s):
            return True
        return max(len(w) for w in non_g) >= 5
    return False


def is_plausible_skill_name(name: str) -> bool:
    """
    False if this looks like a sentence fragment, job description noise, or non-skill.
    Use to avoid storing/displaying phrases like "help accelerate careers" or "321920".
    """
    if not name or not name.strip():
        return False
    s = name.strip()
    if is_blocklisted_skill(s):
        return False
    words = s.split()
    if len(words) > _MAX_SKILL_WORDS:
        return False
    low = s.lower()
    for gw in _GENERIC_SKILL_WORDS:
        if low == gw or low == f"{gw}s":
            return False
    if len(s) > _MAX_SKILL_NAME_LEN:
        return False
    if _SKILL_DIGIT_PATTERN.search(s):
        return False
    if "). " in s or ")." in s or "  " in s:
        return False
    lower = s.lower()
    for frag in _SKILL_SENTENCE_FRAGMENT_PATTERNS:
        if frag in lower:
            return False
    # Job-board / L&D marketing (e.g. "10,000+ courses") — often extracted as a false "skill"
    if re.search(r"\d+\s*\+\s*courses?\b", lower):
        return False
    # Standalone generic words that are often noise
    if lower in ("doing", "comes", "reliable", "pools", "accelerators", "explore du", "cognitive", "comprehend"):
        return False
    # Seniority descriptors from JD text (e.g. "agile seniority level", "mid-level")
    if _SENIORITY_DESCRIPTOR_RE.search(lower):
        return False
    # Culture / personality words (e.g. "camaraderie", "passion", "guru")
    if _normalize_phrase_soft(s) in _CULTURE_PERSONALITY_WORDS:
        return False
    # Single-word industry sector nouns are not learnable technical skills.
    if len(words) == 1 and lower in _INDUSTRY_NOUNS_NOT_SKILLS:
        return False
    if is_soft_skill(s):
        return False
    if not is_tech_or_noun_like_skill(s):
        return False
    return True


def is_high_demand_row_acceptable(name: str) -> bool:
    """
    Extra gates for phrases scraped from job postings (fragments, table noise).
    Used when the local LLM is unavailable; keep in sync with verify_high_demand_missing_skills_llm intent.
    """
    if not is_plausible_skill_name(name):
        return False
    s = name.strip()
    low = s.lower()
    if _looks_like_job_title_or_role(s):
        return False
    if s.count("(") != s.count(")"):
        return False
    if re.search(r"\(e\.g|e\.g\.|etc\.?\s*\)?", low):
        return False
    if re.search(r"\b(both|using)\s+sql\b", low) and "(" in s:
        return False
    return True


def filter_high_demand_rows_heuristic(rows: list[dict]) -> list[dict]:
    """Drop noisy rows when LLM verification is disabled or fails."""
    out: list[dict] = []
    for r in rows:
        name = str(r.get("skill_name") or "").strip()
        if not name:
            continue
        if not is_high_demand_row_acceptable(name):
            continue
        out.append(dict(r))
    return out


# Lazy-loaded KeyBERT model for AI skill extraction (no dictionary)
_keybert_model = None


def _get_keybert_model():
    """Return KeyBERT model backed by the same embedding model as the app (BGE)."""
    global _keybert_model
    if _keybert_model is None:
        from keybert import KeyBERT
        from app.services.embedding_service import _EmbeddingModelSingleton
        _keybert_model = KeyBERT(model=_EmbeddingModelSingleton.get_model())
        logger.info("Loaded KeyBERT for AI skill extraction (no dictionary)")
    return _keybert_model


# Headings that often introduce a skill list (case-insensitive)
_SKILLS_SECTION_HEADINGS = re.compile(
    r"\b(?:skills\s+summary|skills?|technical\s+skills?|expertise|technologies?|tools?\s+&\s+technologies?|core\s+competencies?|key\s+skills?)\s*[:\-]?\s*",
    re.IGNORECASE,
)


def _extract_structured_skills(text: str) -> set[str]:
    """
    Parse resume text for structured skill lists: e.g. "Skills: Python, Java, SQL" or
    bullet lists with comma/semicolon/newline-separated items. Returns cleaned single tokens.
    """
    if not text or not text.strip():
        return set()
    found: set[str] = set()
    # Try to find a block after a skills-related heading (first ~2000 chars after match)
    for m in _SKILLS_SECTION_HEADINGS.finditer(text):
        start = m.end()
        block = text[start : start + 2000]
        # Split on common separators: comma, semicolon, newline, " and ", " • ", " - "
        parts = re.split(r"[\n,;]|\s+and\s+|\s*[•\-]\s+", block)
        for p in parts:
            p = p.strip().strip(".•-–—")
            if 2 <= len(p) <= 80 and not re.match(r"^\d+$", p) and len(p.split()) <= _MAX_SKILL_WORDS:
                found.add(p.strip().lower())
        if found:
            break
    # Also scan first 1500 chars for comma/newline lists (many resumes start with skills)
    if not found:
        block = text[:1500]
        parts = re.split(r"[\n,;]|\s+and\s+", block)
        for p in parts:
            p = p.strip().strip(".•-–—")
            # Allow single- or multi-word skills (e.g. Python, Feature Engineering) but not long sentence fragments
            if 2 <= len(p) <= 60 and not re.match(r"^\d+$", p) and len(p.split()) <= _MAX_SKILL_WORDS:
                found.add(p.strip().lower())
    return found


def _extract_skills_via_ai(text: str) -> set[str]:
    """
    Extract skill-like key phrases from text using KeyBERT (embedding-based keyphrase extraction).
    No dictionary: detects unseen skills and is fully adaptive.
    """
    if not text or not text.strip():
        return set()
    settings = get_settings()
    top_n = min(15, getattr(settings, "skill_extraction_top_n", 15))
    nmin = getattr(settings, "skill_extraction_ngram_min", 1)
    nmax = min(3, getattr(settings, "skill_extraction_ngram_max", 3))
    ngram_range = (nmin, nmax)
    try:
        model = _get_keybert_model()
        # keyphrase_ngram_range: (1, 3) = unigrams to trigrams typical for skills
        keywords = model.extract_keywords(
            text,
            keyphrase_ngram_range=ngram_range,
            top_n=top_n,
            use_mmr=True,
            diversity=0.5,
            stop_words="english",
        )
        found: list[str] = []
        for phrase, _score in keywords or []:
            if not phrase or not isinstance(phrase, str):
                continue
            p = " ".join(phrase.strip().lower().split())
            if len(p) < 2:
                continue
            if len(p.split()) > _MAX_SKILL_WORDS:
                continue
            if p in _GENERIC_SKILL_WORDS or p in ("experienced", "experiences", "teams", "projects"):
                continue
            if not is_tech_or_noun_like_skill(p):
                continue
            found.append(p)
        # Prefer longer phrases: drop a phrase if it is a strict substring of another
        found.sort(key=len, reverse=True)
        seen_lower: set[str] = set()
        kept: set[str] = set()
        for p in found:
            pl = p.lower()
            if pl in seen_lower:
                continue
            if any(pl != o and pl in o for o in seen_lower):
                continue
            seen_lower.add(pl)
            kept.add(p)
        return kept
    except Exception as e:
        logger.warning("AI skill extraction failed: %s", e)
        return set()


def _load_skills_dictionary(path: Path | None = None) -> dict[str, list[str]]:
    p = path or DEFAULT_SKILLS_PATH
    if not p.exists():
        logger.warning("Skills dictionary not found at %s", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _extract_skills_via_dictionary(text: str, skills_dict: dict | None = None) -> set[str]:
    """Legacy: rule-based extraction from skills_dictionary.json. Used only when use_dictionary_skill_extraction=True."""
    if not text or not text.strip():
        return set()
    skills_dict = skills_dict or _load_skills_dictionary()
    text_lower = text.lower()
    found: set[str] = set()
    all_phrases: list[tuple[str, str]] = []
    for _cat, names in skills_dict.items():
        for name in names:
            if name and isinstance(name, str):
                all_phrases.append((name.lower(), name))
    all_phrases.sort(key=lambda x: -len(x[0]))
    for lower_phrase, original in all_phrases:
        if len(lower_phrase) <= 2:
            continue
        if lower_phrase in text_lower:
            found.add(original)
    for lower_phrase, original in all_phrases:
        if " " in lower_phrase:
            continue
        if re.search(rf"\b{re.escape(lower_phrase)}\b", text_lower):
            if lower_phrase == "r" and original == "R":
                if re.search(r"\br\s*&\s*d\b", text_lower) or re.search(r"\br\s+and\s+d\b", text_lower):
                    continue
            found.add(original)
    return found


def extract_skills_from_text(text: str, skills_dict: dict | None = None) -> set[str]:
    """
    Extract skill names from text. Primary path: AI-based (KeyBERT) — no dictionary, adaptive, detects unseen skills.
    Optional: merge with dictionary-based extraction when use_dictionary_skill_extraction=True.
    """
    if not text or not text.strip():
        return set()
    settings = get_settings()
    use_ai = getattr(settings, "use_ai_skill_extraction", True)
    use_dict = getattr(settings, "use_dictionary_skill_extraction", False)

    found: set[str] = set()
    structured = _extract_structured_skills(text)
    if use_ai:
        found = _extract_skills_via_ai(text) | structured
    else:
        found = structured
    if use_dict:
        found |= _extract_skills_via_dictionary(text, skills_dict)
    out: set[str] = set()
    for s in found:
        if not s or is_blocklisted_skill(s):
            continue
        norm = " ".join(str(s).strip().lower().split())
        if is_plausible_skill_name(norm) and is_tech_or_noun_like_skill(norm):
            out.add(norm)
    return out

async def get_or_create_skills(session: AsyncSession, skill_names: set[str] | list[str]) -> list[Skill]:
    """
    Batch upsert skills using INSERT ... ON CONFLICT DO NOTHING then a single
    bulk SELECT.  Replaces the previous per-skill SELECT + INSERT loop which
    issued N DB round-trips (one per skill).  Now costs exactly 2 queries
    regardless of how many skills are provided (typically 15–35 per document).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Deduplicate and filter in one pass
    clean_names: list[str] = []
    for raw in dict.fromkeys(skill_names):  # dict.fromkeys preserves order + deduplicates
        name = " ".join((raw or "").strip().lower().split())
        if name and not is_blocklisted_skill(name) and is_plausible_skill_name(name):
            clean_names.append(name)

    if not clean_names:
        return []

    # 1) Bulk insert — skip rows whose name already exists (ON CONFLICT DO NOTHING)
    insert_stmt = (
        pg_insert(Skill)
        .values([{"name": n, "category": None} for n in clean_names])
        .on_conflict_do_nothing(index_elements=["name"])
    )
    await session.execute(insert_stmt)
    await session.flush()

    # 2) Fetch all rows in a single WHERE name IN (...) query
    select_stmt = select(Skill).where(Skill.name.in_(clean_names))
    rows = (await session.execute(select_stmt)).scalars().all()
    return list(rows)

def _load_role_suggestions(path: Path | None = None) -> dict[str, list[str]]:
    p = path or ROLE_SUGGESTIONS_PATH
    if not p.exists():
        logger.warning("Role suggestions not found at %s", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def get_suggested_roles_for_skills(resume_skill_names: list[str], role_data: dict | None = None) -> list[tuple[str, int]]:
    """Return list of (job_title, relevance_count) sorted by relevance, for roles the user can apply to."""
    role_data = role_data or _load_role_suggestions()
    resume_set = {s.strip().lower() for s in resume_skill_names if s and s.strip()}
    if not resume_set:
        return [(title, 0) for title in role_data]
    out: list[tuple[str, int]] = []
    for title, skills in role_data.items():
        role_skills_lower = {s.strip().lower() for s in skills if s and isinstance(s, str)}
        overlap = len(resume_set & role_skills_lower)
        out.append((title, overlap))
    out.sort(key=lambda x: -x[1])
    return out


def get_synthetic_market_for_role(job_title: str) -> list[str]:
    """Typical skills for this role (from role_suggestions). Used when no scraped jobs exist."""
    role_data = _load_role_suggestions()
    # Match role by case-insensitive title
    for title, skills in role_data.items():
        if title.strip().lower() == job_title.strip().lower():
            return [s for s in skills if s and isinstance(s, str)]
    return list(role_data.values())[0] if role_data else []


def get_synthetic_market_full() -> list[str]:
    """All skills from skills_dictionary (flattened). Used when no scraped jobs exist."""
    skills_dict = _load_skills_dictionary()
    seen: set[str] = set()
    out: list[str] = []
    for names in skills_dict.values():
        for name in names:
            if name and isinstance(name, str) and name not in seen:
                seen.add(name)
                out.append(name)
    return out


async def skill_demand_percentages(session: AsyncSession) -> list[tuple[Skill, int, float]]:
    weight_expr = case(
        (((Job.source == "scraped") & (func.length(func.coalesce(Job.description, "")) < 200)), 0.5),
        else_=1.0,
    )
    total_jobs_stmt = select(func.coalesce(func.sum(weight_expr), 0.0)).select_from(Job)
    total_weight = float((await session.execute(total_jobs_stmt)).scalar() or 0.0)
    if total_weight <= 0:
        return []
    stmt = (
        select(Skill, func.coalesce(func.sum(weight_expr), 0.0).label("job_count"))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .join(Job, Job.id == JobSkill.job_id)
        .group_by(Skill.id)
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[Skill, int, float]] = []
    for skill, job_count in rows:
        w = float(job_count or 0.0)
        out.append((skill, int(round(w)), round((w / total_weight) * 100.0, 2)))
    return out


async def skill_demand_percentages_for_title(
    session: AsyncSession, title_contains: str
) -> list[tuple[Skill, int, float]]:
    """Skill demand only among jobs whose title contains title_contains (case-insensitive)."""
    from app.models import Job
    role_raw = (title_contains or "").strip()
    role_norm = normalize_role(role_raw) if role_raw else ""
    role_queries = expand_role_family(role_norm or role_raw)
    if not role_queries and role_raw:
        role_queries = [role_raw]
    logger.info("ROLE USED (demand): %s", role_norm or role_raw)
    weight_expr = case(
        (((Job.source == "scraped") & (func.length(func.coalesce(Job.description, "")) < 200)), 0.5),
        else_=1.0,
    )
    clauses = [Job.title.ilike(f"%{q}%") for q in role_queries if q]
    if not clauses:
        return []
    total_filter = or_(*clauses)
    total_stmt = select(func.coalesce(func.sum(weight_expr), 0.0)).where(total_filter)
    total_weight = float((await session.execute(total_stmt)).scalar() or 0.0)
    if total_weight <= 0:
        return []
    stmt = (
        select(Skill, func.coalesce(func.sum(weight_expr), 0.0).label("job_count"))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(total_filter)
        .group_by(Skill.id)
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[Skill, int, float]] = []
    for skill, job_count in rows:
        w = float(job_count or 0.0)
        out.append((skill, int(round(w)), round((w / total_weight) * 100.0, 2)))
    return out


# ---------------------------------------------------------------------------
# Two-layer demand-percentages cache.
#
# Problem with the previous version:
#   1. Stored SQLAlchemy ORM Skill objects in a module-level list.
#      After the originating session closes, those objects become detached;
#      accessing any lazy-loaded relationship raises DetachedInstanceError.
#   2. In-process only → not shared across uvicorn workers; each worker
#      ran its own GROUP BY query every 5 minutes independently.
#
# New approach:
#   L1: in-process dict cache, 60 s TTL — avoids Redis round-trip on hot path.
#   L2: Redis key "skill_demand:global", 300 s TTL — shared across all workers.
#   Data: list[dict] with plain Python primitives (no ORM objects).
#
# Return type changed from list[tuple[Skill, int, float]]
#                       to   list[dict]
# All callers in match_service.py have been updated accordingly.
# ---------------------------------------------------------------------------
import json as _json

_DEMAND_REDIS_KEY = "skill_demand:global"
_DEMAND_REDIS_TTL = 300        # seconds — shared Redis TTL
_DEMAND_LOCAL_TTL = 60.0       # seconds — in-process cache window

_demand_local: list[dict] | None = None
_demand_local_ts: float = 0.0


async def skill_demand_percentages_cached(session: AsyncSession) -> list[dict]:
    """
    Returns skill demand as list[dict]:
      {"id": int, "name": str, "category": str|None, "count": int, "pct": float}

    Cache layers (fastest first):
      L1 — in-process dict  (60 s, per-worker, zero network latency)
      L2 — Redis            (300 s, shared across all API workers)
      DB  — GROUP BY fallback when both caches are cold
    """
    global _demand_local, _demand_local_ts
    now = time.monotonic()

    # L1: in-process
    if _demand_local is not None and (now - _demand_local_ts) < _DEMAND_LOCAL_TTL:
        return _demand_local

    # L2: Redis
    from app.cache.redis_client import cache_get, cache_set
    raw = await cache_get(_DEMAND_REDIS_KEY)
    if raw is not None:
        try:
            data: list[dict] = _json.loads(raw)
            _demand_local = data
            _demand_local_ts = now
            return data
        except (ValueError, TypeError):
            pass  # corrupted entry → fall through to DB

    # DB: convert ORM results to plain dicts before caching
    orm_list = await skill_demand_percentages(session)
    data = [
        {"id": s.id, "name": s.name, "category": s.category, "count": cnt, "pct": pct}
        for s, cnt, pct in orm_list
    ]
    _demand_local = data
    _demand_local_ts = now
    await cache_set(_DEMAND_REDIS_KEY, _json.dumps(data).encode(), ttl_seconds=_DEMAND_REDIS_TTL)
    return data


def _skill_usable_in_job_search_query(name: str) -> bool:
    """
    LinkedIn keywords= must be short (≤3 words) and match tech/tool signals — never resume prose.
    """
    t = " ".join((name or "").strip().lower().split())
    words = t.split()
    if len(words) > _MAX_SCRAPE_QUERY_WORDS or len(t) < 2 or len(t) > 48:
        return False
    if t in _GENERIC_SKILL_WORDS:
        return False
    if not _TECH_SKILL_HINT.search(t):
        return False
    return True


def scrape_fallback_search_terms() -> list[str]:
    """Minimal safe keywords when resume/market terms filter to nothing."""
    return list(SCRAPE_QUERY_FALLBACK[:_MAX_SCRAPE_KEYWORDS])


async def invalidate_skill_demand_caches() -> None:
    """Clear L1/L2 demand caches after synthetic jobs or bulk inserts."""
    global _demand_local, _demand_local_ts
    _demand_local = None
    _demand_local_ts = 0.0
    from app.cache.redis_client import cache_delete
    await cache_delete(_DEMAND_REDIS_KEY)


async def get_skills_for_scrape(
    session: AsyncSession,
    *,
    resume_id: int | None = None,
    market_top_n: int = 15,
    extra_skill_names: list[str] | None = None,
) -> list[str]:
    """Combine resume skills (if resume_id) and top market-demand skills for search queries."""
    skill_names: list[str] = []
    if extra_skill_names:
        skill_names.extend(s.strip() for s in extra_skill_names if s and s.strip())
    if resume_id is not None:
        if is_ephemeral_resume_id(resume_id):
            row = get_live_resume_row(resume_id)
            if row:
                for name in row.get("skill_names") or []:
                    if name and name not in skill_names:
                        skill_names.append(name)
        else:
            stmt = select(Skill.name).join(ResumeSkill, ResumeSkill.skill_id == Skill.id).where(
                ResumeSkill.resume_id == resume_id
            )
            rows = (await session.execute(stmt)).scalars().all()
            for name in rows:
                if name and name not in skill_names:
                    skill_names.append(name)
    demand = await skill_demand_percentages(session)
    for skill, _cnt, _pct in demand[:market_top_n]:
        if skill.name and skill.name not in skill_names:
            skill_names.append(skill.name)
    filtered = [s for s in skill_names if _skill_usable_in_job_search_query(s)]
    if not filtered:
        filtered = list(SCRAPE_QUERY_FALLBACK)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in filtered:
        k = s.strip().lower()
        if k and k not in seen:
            seen.add(k)
            deduped.append(s.strip())
    deduped = deduped[:_MAX_SCRAPE_KEYWORDS]
    deduped.sort(key=lambda s: (len(s.split()), len(s)))
    return deduped[:_MAX_SCRAPE_KEYWORDS]


async def skill_trends(
    session: AsyncSession,
    *,
    weeks: int = 8,
    top_emerging_n: int = 15,
) -> tuple[list[dict], list[dict], int]:
    """
    Time-based skill trend analytics. Returns (trends_list, top_emerging_list, weeks_with_data).
    - trends_list: each item has skill_id, skill_name, category, job_count, demand_percentage,
      weekly_growth_pct (last week vs previous week), volatility_index (coefficient of variation of weekly counts).
    - top_emerging_list: skills with positive weekly growth, sorted by growth desc (same shape + is_emerging).
    - weeks_with_data: number of distinct weeks that have job data (need >= 2 for weekly growth).
    Uses Job.created_at for weekly buckets (UTC).
    """
    since = datetime.now(timezone.utc) - timedelta(days=weeks * 7)
    week_trunc = func.date_trunc("week", Job.created_at)
    stmt = (
        select(
            JobSkill.skill_id,
            week_trunc.label("week_start"),
            func.count(Job.id.distinct()).label("job_count"),
        )
        .select_from(JobSkill)
        .join(Job, Job.id == JobSkill.job_id)
        .where(Job.created_at >= since)
        .group_by(JobSkill.skill_id, week_trunc)
    )
    rows = (await session.execute(stmt)).all()
    # (skill_id, week_start, job_count) per row; week_start may be timezone-aware
    by_skill: dict[int, list[tuple[datetime, int]]] = {}
    weeks_seen: set[str] = set()
    for skill_id, week_start, job_count in rows:
        if skill_id not in by_skill:
            by_skill[skill_id] = []
        by_skill[skill_id].append((week_start, job_count))
        weeks_seen.add(week_start.isoformat()[:10] if hasattr(week_start, "isoformat") else str(week_start)[:10])

    # Current demand (all-time) for names and percentages
    demand_list = await skill_demand_percentages(session)
    skill_info: dict[int, tuple[Skill, int, float]] = {}
    for skill, cnt, pct in demand_list:
        skill_info[skill.id] = (skill, cnt, pct)

    trends_list: list[dict] = []
    for skill_id, week_data in by_skill.items():
        if skill_id not in skill_info:
            continue
        skill, job_count, demand_pct = skill_info[skill_id]
        if is_blocklisted_skill(skill.name) or not is_plausible_skill_name(skill.name):
            continue
        week_data.sort(key=lambda x: x[0])
        counts = [c for _, c in week_data]
        if len(week_data) < 2:
            weekly_growth_pct = None
        else:
            last_week_count = week_data[-1][1]
            prev_week_count = week_data[-2][1]
            if prev_week_count and prev_week_count > 0:
                weekly_growth_pct = round((last_week_count - prev_week_count) / prev_week_count * 100.0, 2)
            else:
                weekly_growth_pct = 100.0 if last_week_count else 0.0
        # Volatility: coefficient of variation (std/mean * 100)
        if len(counts) >= 2 and sum(counts) > 0:
            mean_c = np.mean(counts)
            std_c = float(np.std(counts))
            volatility_index = round(std_c / mean_c * 100.0, 2) if mean_c else 0.0
        else:
            volatility_index = 0.0
        trends_list.append({
            "skill_id": skill.id,
            "skill_name": skill.name,
            "category": skill.category,
            "job_count": job_count,
            "demand_percentage": demand_pct,
            "weekly_growth_pct": weekly_growth_pct,
            "volatility_index": volatility_index,
        })

    # Sort by demand desc for main list; top emerging = positive growth, sort by growth desc
    trends_list.sort(key=lambda x: -x["demand_percentage"])
    emerging = [t for t in trends_list if t.get("weekly_growth_pct") is not None and t["weekly_growth_pct"] > 0]
    emerging.sort(key=lambda x: -x["weekly_growth_pct"])
    top_emerging_list = emerging[:top_emerging_n]
    weeks_with_data = len(weeks_seen)
    return (trends_list, top_emerging_list, weeks_with_data)


async def skill_growth_by_name(
    session: AsyncSession,
    *,
    weeks: int = 8,
) -> dict[str, float]:
    """Lowercase skill name → latest weekly_growth_pct (0 if unknown)."""
    trends_list, _, _ = await skill_trends(session, weeks=weeks, top_emerging_n=1200)
    out: dict[str, float] = {}
    for t in trends_list:
        name = (t.get("skill_name") or "").strip().lower()
        g = t.get("weekly_growth_pct")
        if name and g is not None:
            out[name] = float(g)
    return out


async def skill_trends_fastest_declining(
    session: AsyncSession,
    *,
    weeks: int = 8,
    limit: int = 20,
) -> tuple[list[dict], list[dict], int]:
    """(fastest growing, declining, weeks_with_data) using same weekly buckets as skill_trends."""
    trends_list, _, weeks_with_data = await skill_trends(
        session, weeks=weeks, top_emerging_n=max(limit * 6, 80),
    )
    with_g = [t for t in trends_list if t.get("weekly_growth_pct") is not None]
    with_g.sort(key=lambda x: -x["weekly_growth_pct"])
    fastest = with_g[:limit]
    declining = sorted(
        [t for t in with_g if float(t["weekly_growth_pct"]) < 0],
        key=lambda x: float(x["weekly_growth_pct"]),
    )[:limit]
    return fastest, declining, weeks_with_data
