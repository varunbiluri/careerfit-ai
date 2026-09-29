"""
Scraper service — LinkedIn job page scraping.

Key production additions vs the original version:
  - _normalize_text()        : collapse whitespace, strip zero-width chars
  - _is_valid_job_page()     : reject login walls, CAPTCHAs, empty descriptions
  - _fetch_with_retry()      : up to 3 attempts; optional Scrapling AsyncFetcher for linkedin.com
                               when LINKEDIN_USE_SCRAPLING_FETCHER=true, else httpx
  - scrape_and_store()       : sets Job.fetched_at on every new scrape
  - scrape_quick()           : scrapes first max_quick URLs immediately, returns
                               the rest for a background ARQ task
  - scrape_urls()            : scrape an explicit list of URLs (used by background task)
"""
import asyncio
import hashlib
import json
import random
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_utils import run_blocking
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Job, JobSkill, Skill
from app.services.portals.registry import PORTAL_REGISTRY
from app.services.skill_normalizer import normalize_skill_list
from app.services.skill_service import (
    extract_skills_from_text,
    get_or_create_skills,
    scrape_fallback_search_terms,
)
from app.services.job_search_cache import (
    get_cached_search,
    make_job_search_cache_key,
    set_cached_search,
)
from app.services.live_job_registry import (
    register_job,
    snapshot_get,
    snapshot_put,
)

logger = get_logger(__name__)


def _linkedin_serp_kwargs() -> dict[str, object]:
    """Optional LinkedIn query params (f_E, f_WT, f_JT, f_EA) from settings — mirrors common n8n URL builders."""
    s = get_settings()
    return {
        "experience_level": s.linkedin_scraper_experience_filter,
        "remote": s.linkedin_scraper_remote_filter,
        "job_type": s.linkedin_scraper_job_type_filter,
        "easy_apply": s.linkedin_scraper_easy_apply,
    }


def _linkedin_filter_cache_signature() -> str:
    """Stable fragment for job_search_cache keys when LinkedIn SERP filters differ."""
    s = get_settings()
    raw = "|".join(
        [
            (s.linkedin_scraper_experience_filter or "").strip().lower(),
            (s.linkedin_scraper_remote_filter or "").strip().lower(),
            (s.linkedin_scraper_job_type_filter or "").strip().lower(),
            "1" if s.linkedin_scraper_easy_apply else "0",
        ]
    )
    if raw == "|||0":
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# Guaranteed corpus when DB has zero jobs (skills extracted from descriptions).
_SYNTHETIC_FALLBACK_SPECS: tuple[dict[str, str], ...] = (
    {
        "external_id": "synthetic_fallback_ml_eng",
        "title": "Machine Learning Engineer Python PyTorch NLP",
        "company": "Market sample (offline)",
        "description": (
            "Machine Learning Engineer role. Python, PyTorch, TensorFlow, NLP, transformers, "
            "deep learning, Kubernetes, MLflow, experiment design, and model deployment."
        ),
        "url": "https://www.linkedin.com/jobs/search/?keywords=machine%20learning%20engineer",
    },
    {
        "external_id": "synthetic_fallback_data_eng",
        "title": "Data Engineer Airflow SQL Snowflake",
        "company": "Market sample (offline)",
        "description": (
            "Data Engineer building pipelines with Apache Airflow, SQL, Snowflake, Spark, "
            "dbt, ETL, AWS, and data warehousing best practices."
        ),
        "url": "https://www.linkedin.com/jobs/search/?keywords=data%20engineer",
    },
    {
        "external_id": "synthetic_fallback_backend",
        "title": "Backend Engineer APIs Node Python",
        "company": "Market sample (offline)",
        "description": (
            "Backend engineer: REST APIs, Node.js, Python, PostgreSQL, Docker, microservices, "
            "Redis, and distributed systems."
        ),
        "url": "https://www.linkedin.com/jobs/search/?keywords=backend%20engineer",
    },
)


# ── Text helpers ──────────────────────────────────────────────────────────────

def _normalize_text(text: str | None) -> str | None:
    """
    Clean scraped text before storage.
    - Collapse runs of 3+ whitespace/newlines to a paragraph break
    - Collapse multiple spaces within a line
    - Remove zero-width / BOM characters that pollute search and display
    Returns None when the result would be empty.
    """
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", t)   # zero-width chars
    t = re.sub(r"\n{3,}", "\n\n", t)                           # 3+ newlines → paragraph break
    t = re.sub(r"[ \t]{2,}", " ", t)                           # multiple spaces → single
    return t.strip() or None


# ── Validity check ────────────────────────────────────────────────────────────

# Patterns found in LinkedIn login / CAPTCHA / redirect pages — not real job pages
_INVALID_HTML_PATTERNS = (
    "sign in to linkedin",
    "join now to see",
    "authwall",
    "login_submit",
    "session_redirect",
    "checkpoint/challenge",
    "we're sorry, but something went wrong",
    "captcha",
)


def _linkedin_search_html_blocked(html: str) -> bool:
    """
    Heuristic for job *search* pages: captcha / hard auth-wall vs usable SERP.

    LinkedIn often serves ~80k+ HTML without the legacy BEM class names our parser
    used to key off; footer copy like \"join linkedin\" appears on real SERPs too.
    Strong signal: job detail URLs embedded in HTML/JSON (`/jobs/view/`).
    """
    if not html or len(html) < 800:
        return True
    h = html.lower()
    # Real job search payloads almost always reference job IDs in anchors or JSON-LD / state blobs.
    if "/jobs/view/" in h and len(html) >= 4000:
        return False
    # Obvious bot challenges (avoid bare \"captcha\" — it appears in unrelated script strings).
    if any(
        x in h
        for x in (
            "g-recaptcha",
            "hcaptcha.com",
            "/checkpoint/lg/",
            "challengeplatform",
            "captchaenterprise",
            "unusual traffic from your computer network",
        )
    ):
        return True
    looks_like_serp = any(
        x in h
        for x in (
            "jobs-search__results-list",
            "job-card-container",
            "base-card",
            "jobs-search-results",
            "jobs-guest-frontend",
            "jobstoolbar",
            "fsd_jobs",
            "jobsearch",
        )
    )
    if looks_like_serp:
        return False
    # Hard auth wall with little job content
    wall_markers = (
        "authwall",
        "checkpoint/challenge",
        "login_submit",
        "session_redirect",
    )
    if any(m in h for m in wall_markers):
        return True
    if "sign in to linkedin" in h and "/jobs/view/" not in h:
        return True
    return any(p in h for p in _INVALID_HTML_PATTERNS)


def _linkedin_job_signals_present(html: str) -> bool:
    """True when HTML likely contains job posting references (SERP or payload)."""
    if not html:
        return False
    h = html.lower()
    return "/jobs/view/" in h or "urn:li:jobposting" in h


def _search_page_degradation_reason(html: str | None, parsed_links: int) -> str:
    """blocked | empty | success — for logging and scrape_health."""
    if parsed_links > 0:
        return "success"
    if not html or len(html) < 800:
        return "blocked"
    if _linkedin_search_html_blocked(html):
        return "blocked"
    if not _linkedin_job_signals_present(html):
        return "empty"
    return "empty"


async def ensure_synthetic_fallback_jobs(session: AsyncSession) -> int:
    """
    If the jobs table is empty, insert a small synthetic corpus and attach extracted skills.
    Prevents downstream gap/scoring from running on zero-job market data.
    """
    n = int((await session.execute(select(func.count(Job.id)))).scalar() or 0)
    if n > 0:
        return 0
    logger.warning("synthetic_fallback: DB has 0 jobs — inserting guaranteed sample postings")
    inserted = 0
    now = datetime.now(timezone.utc)
    for spec in _SYNTHETIC_FALLBACK_SPECS:
        ex_id = spec["external_id"]
        existing = (
            await session.execute(select(Job.id).where(Job.external_id == ex_id))
        ).scalar_one_or_none()
        if existing is not None:
            continue
        job = Job(
            external_id=ex_id,
            title=spec["title"],
            company=spec["company"],
            description=spec["description"],
            url=spec.get("url"),
            source="synthetic_fallback",
            fetched_at=now,
        )
        session.add(job)
        await session.flush()
        skill_names = await run_blocking(extract_skills_from_text, spec["description"])
        if skill_names:
            skills = await get_or_create_skills(session, skill_names)
            for sk in skills:
                session.add(JobSkill(job_id=job.id, skill_id=sk.id))
        inserted += 1
    if inserted:
        logger.info("synthetic_fallback: inserted %d synthetic job row(s) with skills", inserted)
    return inserted


async def _fetch_search_html_with_retries(
    scraper: "ScraperService",
    search_url: str,
    portal_id: str,
    *,
    attempts: int = 3,
    delay_base: float = 2.5,
) -> tuple[str | None, str | None]:
    """
    GET search page; retry on blocked/empty. Returns (html, final_url) or (None, None).
    """
    last_url: str | None = None
    for attempt in range(attempts):
        await scraper._delay()
        resp = await _fetch_with_retry(search_url, scraper._headers())
        last_url = str(resp.url) if resp else search_url
        if resp is None:
            logger.warning(
                "scraper search fetch failed portal=%s url=%s attempt=%d/%d",
                portal_id,
                search_url[:160],
                attempt + 1,
                attempts,
            )
            if attempt < attempts - 1:
                await asyncio.sleep(delay_base * (attempt + 1))
            continue
        html = resp.text
        if _linkedin_search_html_blocked(html):
            logger.warning(
                "scraper search page blocked or thin HTML portal=%s url=%s attempt=%d/%d len=%d",
                portal_id,
                search_url[:160],
                attempt + 1,
                attempts,
                len(html),
            )
            if attempt < attempts - 1:
                await asyncio.sleep(delay_base * (attempt + 1))
            continue
        logger.info(
            "scraper search ok portal=%s final_url=%s html_len=%d",
            portal_id,
            last_url[:160],
            len(html),
        )
        return html, last_url
    return None, None


def _is_valid_job_page(html: str, description: str | None) -> str | None:
    """
    Classify job page quality:
    - "high"      → description >= 200 chars and no auth-wall/login patterns
    - "degraded"  → description >= 80 chars of text (may contain login text)
    - None        → reject (too short/empty or clearly unusable).

    This keeps the strict gate for high-quality pages while still allowing
    partially useful ones through in a degraded path.
    """
    if not description:
        return None
    desc = description.strip()
    if len(desc) < 80:
        return None

    html_lower = html.lower()
    has_bad = any(p in html_lower for p in _INVALID_HTML_PATTERNS)

    if len(desc) >= 200 and not has_bad:
        return "high"

    # Degraded but usable: some real text, even if login snippets are present.
    return "degraded"


# ── HTTP helper with retry ─────────────────────────────────────────────────────

def _httpx_response_from_text(url: str, text: str, status_code: int = 200) -> httpx.Response:
    """Build an httpx.Response so downstream code can keep using resp.text unchanged."""
    req = httpx.Request("GET", url)
    return httpx.Response(
        status_code,
        content=text.encode("utf-8"),
        request=req,
    )


async def _fetch_linkedin_via_scrapling(url: str) -> httpx.Response | None:
    """
    Optional path: Scrapling's AsyncFetcher (curl_cffi TLS impersonation + stealth headers).
    No Playwright browser required; falls back to httpx on failure.
    """
    try:
        from scrapling.fetchers import AsyncFetcher
    except ImportError:
        logger.debug("scrapling not installed; skipping Scrapling fetch")
        return None
    try:
        r = await AsyncFetcher.get(url, impersonate="chrome", stealthy_headers=True)
        status = getattr(r, "status", None)
        if status != 200:
            logger.warning(
                "scraper scrapling: non-200 url=%s status=%s",
                url[:120],
                status,
            )
            return None
        html = str(r.html_content)
        if len(html) < 500:
            logger.warning(
                "scraper scrapling: suspiciously short HTML url=%s len=%d",
                url[:120],
                len(html),
            )
            return None
        return _httpx_response_from_text(url, html, 200)
    except Exception as exc:
        logger.warning(
            "scraper scrapling fetch failed url=%s: %s",
            url[:120],
            exc,
        )
        return None


async def _fetch_with_retry(
    url: str,
    headers: dict[str, str],
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> httpx.Response | None:
    """
    GET url with exponential back-off on 429 / 5xx / network errors.

    Back-off schedule (base_delay=2):
      attempt 0 → immediate
      attempt 1 → ~2 s  + jitter
      attempt 2 → ~4 s  + jitter
      attempt 3 → ~8 s  + jitter

    Returns the Response on success, None after all attempts fail.
    """
    settings = get_settings()
    if settings.linkedin_use_scrapling_fetcher and "linkedin.com" in (url or "").lower():
        scrap = await _fetch_linkedin_via_scrapling(url)
        if scrap is not None:
            logger.debug("scraper using Scrapling response url=%s", url[:120])
            return scrap
        logger.debug(
            "scraper Scrapling failed or unavailable; using httpx url=%s",
            url[:120],
        )

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            await asyncio.sleep(random.uniform(1.5, 3.0))
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=10.0, headers=headers
            ) as client:
                resp = await client.get(url)

            if resp.status_code == 429:
                # Rate-limited by LinkedIn — must back off
                wait = base_delay * (2 ** attempt) + random.uniform(0.5, 1.5)
                logger.warning(
                    "scraper 429 url=%s attempt=%d backing off %.1fs",
                    url[:80], attempt, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                    continue
                return None

            resp.raise_for_status()
            return resp

        except (httpx.HTTPStatusError, httpx.RequestError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt) + random.uniform(0.5, 1.5)
                logger.debug(
                    "scraper fetch error url=%s attempt=%d retrying in %.1fs: %s",
                    url[:80], attempt, wait, exc,
                )
                await asyncio.sleep(wait)

    logger.warning("scraper fetch failed url=%s after %d attempts: %s", url[:80], max_retries + 1, last_exc)
    return None


# ── Misc helpers ──────────────────────────────────────────────────────────────

def _external_id_from_url(url: str) -> str:
    return "scraped_" + hashlib.sha256(url.encode()).hexdigest()[:32]


# LinkedIn job listing → only canonical view URLs (https://www.linkedin.com/jobs/view/<id>)
_LINKEDIN_JOB_VIEW_ID_RE = re.compile(r"/jobs/view/(\d+)", re.IGNORECASE)


def _linkedin_job_url_rejected(url: str) -> bool:
    """True when URL must not be stored or fetched (authwall / tracking / search)."""
    u = (url or "").lower()
    return (
        "search?" in u
        or "redirect" in u
        or "trk=" in u
        or "guestredirect" in u
    )


def _canonical_linkedin_job_url_or_none(url: str) -> str | None:
    """
    Extract numeric job id via /jobs/view/(\\d+), rebuild canonical URL, or None if invalid.
    """
    s = (url or "").strip()
    if not s or _linkedin_job_url_rejected(s):
        return None
    if "/jobs/view/" not in s.lower():
        return None
    if "linkedin.com" not in s.lower():
        return None
    m = _LINKEDIN_JOB_VIEW_ID_RE.search(s)
    if not m:
        return None
    job_id = m.group(1)
    if not job_id:
        return None
    if len(job_id) < 6:
        return None
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def _sanitize_linkedin_job_listing_urls(urls: list[str]) -> list[str]:
    """Filter parsed SERP links to canonical view URLs only, stable order, deduped."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        c = _canonical_linkedin_job_url_or_none(raw)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _linkedin_html_has_job_top_markup(html_lower: str) -> bool:
    """
    LinkedIn serves at least two public job-detail templates: logged-in style uses
    jobs-unified-top-card; guest / SEO pages often use top-card-layout + decorated-job-posting.
    """
    return (
        "jobs-unified-top-card" in html_lower
        or "top-card-layout" in html_lower
        or "decorated-job-posting__details" in html_lower
    )


def _linkedin_html_has_job_body(html_lower: str) -> bool:
    """True when the response includes the main job description region (guest or member view)."""
    return (
        "description__text--rich" in html_lower
        or "show-more-less-html__markup" in html_lower
        or "decorated-job-posting__details" in html_lower
    )


def _text(el) -> str | None:
    if el is None:
        return None
    t = el.get_text(separator=" ", strip=True)
    return t if t else None


def _clean_job_title(title: str | None) -> str | None:
    """Remove LinkedIn boilerplate appended to job titles."""
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


def _parse_iso_datetime_z(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_job_posting_node(obj: dict) -> bool:
    t = obj.get("@type")
    if t == "JobPosting":
        return True
    if isinstance(t, list):
        return "JobPosting" in t
    return False


def _walk_json_ld_for_job_postings(data: object, depth: int = 0) -> list[dict]:
    if depth > 24:
        return []
    out: list[dict] = []
    if isinstance(data, dict):
        if _is_job_posting_node(data):
            out.append(data)
        g = data.get("@graph")
        if isinstance(g, list):
            for x in g:
                out.extend(_walk_json_ld_for_job_postings(x, depth + 1))
        for v in data.values():
            if isinstance(v, (dict, list)):
                out.extend(_walk_json_ld_for_job_postings(v, depth + 1))
    elif isinstance(data, list):
        for x in data:
            out.extend(_walk_json_ld_for_job_postings(x, depth + 1))
    return out


def _linkedin_job_posting_meta(soup: BeautifulSoup) -> tuple[str | None, datetime | None]:
    """Company name + datePosted from JSON-LD JobPosting when LinkedIn embeds it."""
    company: str | None = None
    posted: datetime | None = None
    for script in soup.find_all("script", type=lambda x: x and "ld+json" in str(x).lower()):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for jp in _walk_json_ld_for_job_postings(data):
            org = jp.get("hiringOrganization") or {}
            if isinstance(org, dict):
                name = org.get("name")
                if isinstance(name, str) and name.strip():
                    company = company or name.strip()
            dp = jp.get("datePosted") or jp.get("dateposted")
            if isinstance(dp, str) and dp.strip():
                parsed = _parse_iso_datetime_z(dp)
                if parsed:
                    posted = posted or parsed
    return company, posted


def _linkedin_company_from_company_links(soup: BeautifulSoup) -> str | None:
    """Fallback: visible text on LinkedIn company profile links."""
    for a in soup.select('a[href*="linkedin.com/company/"]'):
        t = _text(a)
        if not t:
            continue
        tl = t.lower()
        if "linkedin" in tl and len(t) < 30:
            continue
        if len(t.strip()) > 2:
            return t.strip()
    return None


_REL_AGO = re.compile(
    r"\b(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)


def _timedelta_from_ago_match(m: re.Match) -> timedelta | None:
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("second"):
        return timedelta(seconds=n)
    if unit.startswith("minute"):
        return timedelta(minutes=n)
    if unit.startswith("hour"):
        return timedelta(hours=n)
    if unit.startswith("day"):
        return timedelta(days=n)
    if unit.startswith("week"):
        return timedelta(weeks=n)
    if unit.startswith("month"):
        return timedelta(days=30 * n)
    if unit.startswith("year"):
        return timedelta(days=365 * n)
    return None


def _linkedin_relative_posted_at(soup: BeautifulSoup, html: str, now: datetime) -> datetime | None:
    """Approximate listing time from LinkedIn 'N hours ago' in the job top card (not similar jobs)."""
    if not html:
        return None
    for container in (
        soup.find(class_=lambda c: c and "jobs-unified-top-card" in str(c).lower()),
        soup.find(class_=lambda c: c and "top-card-layout" in str(c).lower()),
        soup.find(class_=lambda c: c and "topcard" in str(c).lower()),
    ):
        if container:
            m = _REL_AGO.search(container.get_text(" ", strip=True))
            if m:
                delta = _timedelta_from_ago_match(m)
                if delta is not None:
                    return now - delta
    m = _REL_AGO.search(html[:300_000])
    if not m:
        return None
    delta = _timedelta_from_ago_match(m)
    return now - delta if delta is not None else None


def _extract_seniority_and_function(title: str | None) -> tuple[str | None, str | None]:
    """Classify seniority level and functional area from job title."""
    if not title:
        return None, None
    title_lower = title.lower()
    # Order matters: "Senior" before "Lead" so titles like "Senior Developer / Lead"
    # classify as Senior (tier), not Lead (suffix role variant).
    seniority_patterns = [
        ("chief", "C-Level"), ("vp", "VP"), ("vice president", "VP"),
        ("director", "Director"), ("head of", "Director"), ("manager", "Manager"),
        ("principal", "Principal"), ("senior", "Senior"), ("staff", "Staff"),
        ("lead", "Lead"),
        ("intermediate", "Intermediate"), ("mid", "Mid-Level"),
        ("mid-level", "Mid-Level"), ("associate", "Associate"), ("junior", "Junior"),
        ("entry", "Entry-Level"), ("entry-level", "Entry-Level"), ("intern", "Intern"),
    ]
    function_patterns = [
        ("data scientist", "Data Science"), ("data engineer", "Data Engineering"),
        ("machine learning engineer", "ML/AI"), ("ml engineer", "ML/AI"),
        ("ai engineer", "ML/AI"), ("software engineer", "Engineering"),
        ("software developer", "Engineering"), ("backend engineer", "Engineering"),
        ("frontend engineer", "Engineering"), ("full stack engineer", "Engineering"),
        ("full stack developer", "Engineering"), ("devops engineer", "Engineering"),
        ("sre", "Engineering"), ("site reliability engineer", "Engineering"),
        ("product manager", "Product"), ("product owner", "Product"),
        ("marketing manager", "Marketing"), ("marketing", "Marketing"),
        ("sales manager", "Sales"), ("sales", "Sales"),
        ("business analyst", "Business"), ("data analyst", "Data Science"),
        ("research scientist", "Research"), ("research engineer", "Research"),
        ("qa engineer", "Engineering"), ("quality assurance engineer", "Engineering"),
        ("security engineer", "Security"), ("security analyst", "Security"),
        ("engineer", "Engineering"), ("developer", "Engineering"),
    ]
    seniority = next((lvl for pat, lvl in seniority_patterns if pat in title_lower), None)
    function  = next((fn  for pat, fn  in function_patterns  if pat in title_lower), None)
    return seniority, function


# ── Main service ──────────────────────────────────────────────────────────────

class ScraperService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }

    async def _delay(self) -> None:
        """Polite crawl delay between requests (configurable via SCRAPER_DELAY_SECONDS)."""
        await asyncio.sleep(self.settings.scraper_delay_seconds)

    # ── Cache check ───────────────────────────────────────────────────────────

    async def count_jobs_total(self) -> int:
        n = (await self.session.execute(select(func.count(Job.id)))).scalar()
        return int(n or 0)

    async def is_cached(self, url: str) -> bool:
        """True when a recent version of this URL already exists in the DB."""
        external_id = _external_id_from_url(url)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.scraper_cache_days)
        stmt = select(Job).where(
            Job.external_id == external_id,
            Job.updated_at >= cutoff,
        )
        row = (await self.session.execute(stmt)).scalars().one_or_none()
        return row is not None

    async def _skill_names_for_job(self, job_id: int) -> list[str]:
        """Skill names linked to a stored job (cache-hit path for live corpus)."""
        stmt = (
            select(Skill.name)
            .join(JobSkill, JobSkill.skill_id == Skill.id)
            .where(JobSkill.job_id == job_id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [str(r) for r in rows if r]

    # ── Single-URL scrape ─────────────────────────────────────────────────────

    async def scrape_and_store(self, url: str, source: str = "scraped") -> tuple[Job | SimpleNamespace | None, list[str]]:
        """
        Scrape one job URL. If persist_scraped_jobs is True, write Job + JobSkill to PostgreSQL.
        If False, keep the listing in live_job_registry only (live HTML-derived data, no DB rows).
        """
        settings = get_settings()
        persist = settings.persist_scraped_jobs

        if "linkedin.com" in (url or "").lower():
            canon = _canonical_linkedin_job_url_or_none(url)
            if not canon:
                logger.info(
                    "scraper: skip invalid LinkedIn job URL url=%s",
                    (url or "")[:120],
                )
                return None, []
            url = canon

        external_id = _external_id_from_url(url)

        if persist:
            if await self.is_cached(url):
                logger.debug("cache hit url=%s", url[:80])
                stmt = select(Job).where(Job.external_id == external_id)
                job = (await self.session.execute(stmt)).scalars().one_or_none()
                if job is None:
                    return None, []
                skills = await self._skill_names_for_job(job.id)
                return job, skills
        else:
            cached = snapshot_get(external_id)
            if cached:
                logger.debug("cache hit (memory) url=%s", url[:80])
                ns = SimpleNamespace(
                    id=cached["id"],
                    external_id=cached["external_id"],
                    title=cached.get("title"),
                    company=cached.get("company"),
                    seniority_level=cached.get("seniority_level"),
                    function=cached.get("function"),
                    description=cached.get("description") or "",
                    url=cached.get("url"),
                    source=cached.get("source") or source,
                    fetched_at=cached.get("fetched_at"),
                    listing_posted_at=cached.get("listing_posted_at"),
                )
                return ns, list(cached.get("skill_names") or [])

        await self._delay()

        resp = await _fetch_with_retry(url, self._headers())
        if resp is None:
            logger.warning("scraper: no response after retries url=%s", url[:120])
            return None, []

        html = resp.text

        if "linkedin.com" in (url or "").lower():
            html_lower = (html or "").lower()
            if not _linkedin_html_has_job_top_markup(html_lower):
                logger.warning(
                    "scraper: LinkedIn HTML missing job top/detail markup (possible authwall) url=%s — retrying once",
                    url[:120],
                )
                await asyncio.sleep(random.uniform(1.5, 3.0))
                resp = await _fetch_with_retry(url, self._headers())
                if resp is None:
                    logger.warning("scraper: retry fetch failed url=%s", url[:120])
                    return None, []
                html = resp.text
                html_lower = (html or "").lower()
                if not _linkedin_html_has_job_top_markup(html_lower):
                    logger.warning(
                        "scraper: LinkedIn job page still invalid after retry (no job markup) url=%s",
                        url[:120],
                    )
                    return None, []
            # Guest pages always include Sign in / Join CTAs; only treat hard failures.
            if "authwall" in html_lower:
                logger.warning(
                    "scraper: LinkedIn page shows authwall url=%s",
                    url[:120],
                )
                return None, []
            if "not found" in html_lower and not _linkedin_html_has_job_body(html_lower):
                logger.warning(
                    "scraper: LinkedIn page looks like not-found without job body url=%s",
                    url[:120],
                )
                return None, []

        # ── Parse ─────────────────────────────────────────────────────────────
        soup = BeautifulSoup(html, "html.parser")
        title = _text(soup.find("h1")) or _text(soup.find("title"))
        title = _clean_job_title(title) or title

        company_el = (
            soup.find(class_=lambda c: c and "company" in c.lower())
            or soup.find("span", class_=lambda c: c and "company" in str(c).lower())
        )
        company = _text(company_el) if company_el else None

        desc_el = (
            soup.find(class_=lambda c: c and "description" in c.lower())
            or soup.find("div", {"id": "job-description"})
            or soup.find("article")
            or soup.find("main")
        )
        raw_description = _text(desc_el) if desc_el else (
            soup.get_text(separator=" ", strip=True)[:15000]
        )

        # ── Validate ──────────────────────────────────────────────────────────
        quality = _is_valid_job_page(html, raw_description)
        if quality is None:
            logger.info(
                "scraper: invalid/empty page rejected url=%s (login wall or no description)",
                url[:120],
            )
            return None, []

        # ── Normalize ────────────────────────────────────────────────────────
        description = _normalize_text(raw_description)
        now = datetime.now(timezone.utc)
        title       = _normalize_text(title) or "Unknown"
        company     = _normalize_text(company)
        listing_posted_at: datetime | None = None

        if "linkedin.com" in (url or "").lower():
            jp_co, jp_dt = _linkedin_job_posting_meta(soup)
            if jp_co:
                company = _normalize_text(jp_co) or company
            if not company:
                company = _normalize_text(_linkedin_company_from_company_links(soup))
            listing_posted_at = jp_dt or _linkedin_relative_posted_at(soup, html, now)

        seniority_level, function = _extract_seniority_and_function(title)

        # ── Skills ────────────────────────────────────────────────────────────
        # For degraded pages, enrich skill text with title-derived hints so
        # partially blocked LinkedIn pages still contribute useful signal.
        text_for_skills = description or ""
        if quality == "degraded":
            t_low = (title or "").lower()
            kw: list[str] = []
            if "machine learning" in t_low or re.search(r"\bml\b", t_low):
                kw.append("machine learning")
            elif "data engineer" in t_low:
                kw.append("data engineering")
            elif "backend" in t_low:
                kw.append("backend")
            text_for_skills = " ".join([title or "", *kw[:3], description or ""]).strip()

        # KeyBERT inference is CPU-bound — off-load to executor
        skill_names = await run_blocking(extract_skills_from_text, text_for_skills)
        out_skills: list[str] = []

        if persist:
            job = Job(
                external_id=external_id,
                title=title,
                company=company,
                seniority_level=seniority_level,
                function=function,
                description=description or "",
                url=url,
                source=source,
                fetched_at=now,
                listing_posted_at=listing_posted_at,
            )
            if quality == "degraded":
                setattr(job, "source_quality", "low")
                setattr(job, "is_degraded", True)
            else:
                setattr(job, "source_quality", "high")
                setattr(job, "is_degraded", False)
            self.session.add(job)
            await self.session.flush()

            if skill_names:
                skills = await get_or_create_skills(self.session, skill_names)
                for skill in skills:
                    self.session.add(JobSkill(job_id=job.id, skill_id=skill.id))
                await self.session.flush()
                out_skills = [s.name for s in skills]
            return job, out_skills

        # Ephemeral: no PostgreSQL rows.
        out_skills = normalize_skill_list(skill_names) if skill_names else []
        payload = {
            "external_id": external_id,
            "title": title,
            "company": company,
            "seniority_level": seniority_level,
            "function": function,
            "description": description or "",
            "url": url,
            "source": source,
            "fetched_at": now,
            "listing_posted_at": listing_posted_at,
            "skill_names": out_skills,
        }
        jid = register_job(payload)
        snapshot_put(external_id, {**payload, "id": jid})
        ns = SimpleNamespace(
            id=jid,
            external_id=external_id,
            title=title,
            company=company,
            seniority_level=seniority_level,
            function=function,
            description=description or "",
            url=url,
            source=source,
            fetched_at=now,
            listing_posted_at=listing_posted_at,
        )
        return ns, out_skills

    # ── Multi-URL scrape ──────────────────────────────────────────────────────

    async def scrape_urls(self, urls: list[str], source: str = "linkedin") -> dict:
        """
        Scrape an explicit list of URLs.  Used by the background_scrape_task ARQ
        job so the remaining (non-quick) URLs are processed asynchronously.
        """
        new_count = cached_count = 0
        errors: list[str] = []
        # Limit concurrent network/parse work to avoid request bursts and keep
        # scraper stable under larger URL batches.
        semaphore = asyncio.Semaphore(10)

        async def _bounded_fetch(url: str) -> tuple[bool, bool, str | None]:
            # Concurrency cap (10) balances throughput and LinkedIn throttling risk.
            async with semaphore:
                try:
                    was_cached = await self.is_cached(url)
                    job, _skills = await self.scrape_and_store(url, source=source)
                    return (job is not None, was_cached, None)
                except Exception as exc:
                    logger.warning("scrape_urls error url=%s: %s", url[:60], exc)
                    return (False, False, f"{url[:60]}… → {exc}")

        results = await asyncio.gather(
            *[_bounded_fetch(url) for url in urls],
            return_exceptions=False,
        )
        for ok, was_cached, err in results:
            if err:
                errors.append(err)
                continue
            if ok:
                if was_cached:
                    cached_count += 1
                else:
                    new_count += 1
        return {"total_new": new_count, "total_cached": cached_count, "errors": errors}

    # ── Progressive scrape ────────────────────────────────────────────────────

    async def scrape_quick(
        self,
        skill_terms: list[str],
        portal_ids: list[str] | None = None,
        max_quick: int = 5,
        posted_within_hours: int | None = None,
        location: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> tuple[dict, list[str]]:
        """
        Two-phase scrape:
          1. Discover all job URLs from the search results page.
          2. Immediately scrape the first max_quick URLs (fast, unblocks the user).
          3. Return the rest of the discovered URLs for a background ARQ task.

        Returns:
          (result_dict, remaining_urls)
          result_dict has the same shape as scrape_by_skills().
        """
        if not skill_terms:
            return (
                {
                    "portals": {},
                    "total_new": 0,
                    "total_cached": 0,
                    "errors": ["No skill terms provided"],
                    "links_parsed_total": 0,
                    "scraped_quick_jobs": 0,
                    "market_scrape_degraded": True,
                    "db_jobs_count": 0,
                    "scrape_health": {"links_found": 0, "is_degraded": True, "reason": "empty"},
                    "live_job_corpus": [],
                },
                [],
            )

        portals = {
            pid: PORTAL_REGISTRY[pid]
            for pid in (portal_ids or list(PORTAL_REGISTRY.keys()))
            if pid in PORTAL_REGISTRY
        }
        if not portals:
            return (
                {
                    "portals": {},
                    "total_new": 0,
                    "total_cached": 0,
                    "errors": ["No valid portal IDs"],
                    "links_parsed_total": 0,
                    "scraped_quick_jobs": 0,
                    "market_scrape_degraded": True,
                    "db_jobs_count": 0,
                    "scrape_health": {"links_found": 0, "is_degraded": True, "reason": "blocked"},
                    "live_job_corpus": [],
                },
                [],
            )

        cache_key = make_job_search_cache_key(
            skill_terms=skill_terms,
            location=location,
            posted_within_hours=posted_within_hours,
            mode="quick",
            max_jobs_hint=max_quick,
            portal_signature=",".join(sorted(portals.keys())),
            linkedin_filter_signature=_linkedin_filter_cache_signature(),
        )
        if not force_refresh:
            cached = await get_cached_search(cache_key)
            if cached and isinstance(cached.get("result"), dict):
                result = dict(cached["result"])
                result["db_jobs_count"] = await self.count_jobs_total()
                result.setdefault("live_job_corpus", [])
                rem = list(cached.get("remaining_urls") or [])
                logger.info("scrape_quick served from job_search_cache key=%s", cache_key[:12])
                return result, rem
        else:
            logger.info("scrape_quick: bypassing cache for fresh fetch")

        total_new = total_cached = 0
        errors: list[str] = []
        per_portal: dict[str, dict] = {}
        all_remaining: list[str] = []

        links_parsed_total = 0
        fallback_terms = scrape_fallback_search_terms()
        live_job_corpus: list[dict[str, object]] = []

        for pid, adapter in portals.items():
            async def _run_search(
                terms: list[str],
                hours: int | None,
                loc: str | None,
                portal=adapter,
                portal_id=pid,
            ) -> tuple[list[str], str | None, str | None]:
                u = portal.build_search_url(
                    terms,
                    max_results=max_quick * 3,
                    posted_within_hours=hours,
                    location=loc,
                    **_linkedin_serp_kwargs(),
                )
                logger.info(
                    "scraper scrape_quick portal=%s keywords=%s url=%s",
                    portal_id,
                    terms,
                    u[:220],
                )
                h, base = await _fetch_search_html_with_retries(self, u, portal_id)
                if not h or not base:
                    return [], None, None
                found = _sanitize_linkedin_job_listing_urls(portal.parse_job_links(h, base))
                logger.info(
                    "scraper scrape_quick portal=%s links_found=%d degradation_if_empty=%s",
                    portal_id,
                    len(found),
                    _search_page_degradation_reason(h, len(found)),
                )
                return found, h, base

            per_portal[pid] = {
                "new": 0,
                "cached": 0,
                "links_found": 0,
                "quick": 0,
                "error": None,
                "degradation_reason": "blocked",
            }
            job_urls: list[str] = []
            effective_html: str | None = None
            try:
                try:
                    job_urls, effective_html, final_base = await asyncio.wait_for(
                        _run_search(skill_terms, posted_within_hours, location),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("scrape_quick portal=%s primary search timeout", pid)
                    job_urls, effective_html, final_base = [], None, None
                if not job_urls and posted_within_hours is not None:
                    try:
                        job_urls, effective_html, final_base = await asyncio.wait_for(
                            _run_search(skill_terms, None, location),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_quick portal=%s relaxed search timeout", pid)
                        job_urls, effective_html, final_base = [], None, None
                if not job_urls:
                    try:
                        job_urls, effective_html, final_base = await asyncio.wait_for(
                            _run_search(fallback_terms, None, location),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_quick portal=%s fallback(location) timeout", pid)
                        job_urls, effective_html, final_base = [], None, None
                if not job_urls:
                    try:
                        job_urls, effective_html, final_base = await asyncio.wait_for(
                            _run_search(fallback_terms, None, None),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_quick portal=%s fallback(global) timeout", pid)
                        job_urls, effective_html, final_base = [], None, None

                if effective_html is None:
                    per_portal[pid]["error"] = "Search page fetch failed or blocked after retries"
                    per_portal[pid]["degradation_reason"] = "blocked"
                    errors.append(f"{pid}: search page unavailable or blocked")
                    continue

                deg = _search_page_degradation_reason(effective_html, len(job_urls))
                per_portal[pid]["degradation_reason"] = deg
                per_portal[pid]["links_found"] = len(job_urls)
                links_parsed_total += len(job_urls)

                if not job_urls:
                    errors.append(f"{pid}: parsed_links=0 after retries (reason={deg})")
                    continue

                quick_urls = job_urls[:max_quick]
                remaining_urls = job_urls[max_quick:]
                all_remaining.extend(remaining_urls)
                per_portal[pid]["quick"] = len(quick_urls)

                for url in quick_urls:
                    try:
                        persist_jobs = get_settings().persist_scraped_jobs
                        was_cached = await self.is_cached(url) if persist_jobs else False
                        try:
                            job, skill_names_row = await asyncio.wait_for(
                                self.scrape_and_store(url, source=pid), timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning("scrape_quick detail timeout portal=%s url=%s", pid, url[:80])
                            continue
                        if job:
                            desc = (getattr(job, "description", None) or "")[:1200]
                            live_job_corpus.append(
                                {
                                    "title": job.title or "",
                                    "skills": skill_names_row,
                                    "description": desc,
                                }
                            )
                            if was_cached:
                                per_portal[pid]["cached"] += 1
                                total_cached += 1
                            else:
                                per_portal[pid]["new"] += 1
                                total_new += 1
                    except Exception as exc:
                        logger.warning("scrape_quick error url=%s: %s", url[:60], exc)
                        errors.append(f"{pid}: {url[:50]}… → {exc}")

            except Exception as exc:
                logger.warning("scrape_quick portal %s search failed: %s", pid, exc)
                per_portal[pid]["error"] = str(exc)
                per_portal[pid]["degradation_reason"] = "blocked"
                errors.append(f"{pid}: {exc}")

        scraped_quick = total_new + total_cached
        db_n = await self.count_jobs_total()
        market_scrape_degraded = links_parsed_total == 0 or scraped_quick == 0
        health_reason = "success"
        if links_parsed_total == 0:
            health_reason = "blocked"
            for pdata in per_portal.values():
                if pdata.get("degradation_reason") == "empty":
                    health_reason = "empty"
                    break
        elif scraped_quick == 0:
            health_reason = "empty"

        if market_scrape_degraded:
            msg = (
                f"No jobs scraped in quick batch (parsed {links_parsed_total} search links; "
                f"{db_n} jobs in DB cache for market signals)."
            )
            errors.append(msg)
            logger.warning("scraper NEVER silent-empty: %s", msg)

        scrape_health = {
            "links_found": links_parsed_total,
            "is_degraded": market_scrape_degraded,
            "reason": health_reason,
        }
        logger.info(
            "scraper scrape_quick summary keywords=%s links_found=%d degraded=%s reason=%s",
            skill_terms[:5],
            links_parsed_total,
            market_scrape_degraded,
            health_reason,
        )

        result = {
            "portals": per_portal,
            "total_new": total_new,
            "total_cached": total_cached,
            "errors": errors,
            "links_parsed_total": links_parsed_total,
            "scraped_quick_jobs": scraped_quick,
            "market_scrape_degraded": market_scrape_degraded,
            "db_jobs_count": db_n,
            "scrape_health": scrape_health,
            "live_job_corpus": live_job_corpus,
        }
        await set_cached_search(
            cache_key,
            result=result,
            remaining_urls=all_remaining,
            source="scrape",
        )
        return result, all_remaining

    # ── Original full scrape (preserved for cron pre-scrape and fallback) ─────

    async def scrape_by_skills(
        self,
        skill_terms: list[str],
        portal_ids: list[str] | None = None,
        max_per_portal: int = 15,
        posted_within_hours: int | None = None,
        location: str | None = None,
    ) -> dict:
        """
        Full scrape of up to max_per_portal jobs per portal.
        Preserved for prescrape_jobs cron and direct callers; not used by the
        progressive gap analysis path (which calls scrape_quick instead).
        """
        if not skill_terms:
            return {
                "portals": {},
                "total_new": 0,
                "total_cached": 0,
                "errors": ["No skill terms provided"],
                "links_parsed_total": 0,
                "db_jobs_count": 0,
                "scrape_health": {"links_found": 0, "is_degraded": True, "reason": "empty"},
            }

        portals = {
            pid: PORTAL_REGISTRY[pid]
            for pid in (portal_ids or list(PORTAL_REGISTRY.keys()))
            if pid in PORTAL_REGISTRY
        }
        if not portals:
            return {
                "portals": {},
                "total_new": 0,
                "total_cached": 0,
                "errors": ["No valid portal IDs"],
                "links_parsed_total": 0,
                "db_jobs_count": 0,
                "scrape_health": {"links_found": 0, "is_degraded": True, "reason": "blocked"},
            }

        cache_key = make_job_search_cache_key(
            skill_terms=skill_terms,
            location=location,
            posted_within_hours=posted_within_hours,
            mode="full",
            max_jobs_hint=max_per_portal,
            portal_signature=",".join(sorted(portals.keys())),
            linkedin_filter_signature=_linkedin_filter_cache_signature(),
        )
        cached = await get_cached_search(cache_key)
        if cached and isinstance(cached.get("result"), dict):
            result = dict(cached["result"])
            result["db_jobs_count"] = await self.count_jobs_total()
            logger.info("scrape_by_skills served from job_search_cache key=%s", cache_key[:12])
            return result

        total_new = total_cached = 0
        errors: list[str] = []
        per_portal: dict[str, dict] = {}
        fb_terms = scrape_fallback_search_terms()

        for pid, adapter in portals.items():
            per_portal[pid] = {"new": 0, "cached": 0, "links_found": 0, "error": None}
            try:
                search_url = adapter.build_search_url(
                    skill_terms,
                    max_results=max_per_portal,
                    posted_within_hours=posted_within_hours,
                    location=location,
                    **_linkedin_serp_kwargs(),
                )
                logger.info(
                    "scraper scrape_by_skills keywords=%s url=%s portal=%s",
                    skill_terms[:5],
                    search_url[:200],
                    pid,
                )
                try:
                    html, final_base = await asyncio.wait_for(
                        _fetch_search_html_with_retries(self, search_url, pid),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("scrape_by_skills portal=%s primary search timeout", pid)
                    html, final_base = None, None
                job_urls: list[str] = []
                effective_html = html
                if html and final_base:
                    job_urls = _sanitize_linkedin_job_listing_urls(
                        adapter.parse_job_links(html, final_base)
                    )
                if not job_urls and posted_within_hours is not None:
                    relaxed_url = adapter.build_search_url(
                        skill_terms,
                        max_results=max_per_portal,
                        posted_within_hours=None,
                        location=location,
                        **_linkedin_serp_kwargs(),
                    )
                    try:
                        h2, b2 = await asyncio.wait_for(
                            _fetch_search_html_with_retries(self, relaxed_url, pid),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_by_skills portal=%s relaxed search timeout", pid)
                        h2, b2 = None, None
                    if h2 and b2:
                        job_urls = _sanitize_linkedin_job_listing_urls(
                            adapter.parse_job_links(h2, b2)
                        )
                        effective_html = h2
                if not job_urls:
                    u3 = adapter.build_search_url(
                        fb_terms,
                        max_results=max_per_portal,
                        posted_within_hours=None,
                        location=location,
                        **_linkedin_serp_kwargs(),
                    )
                    try:
                        h3, b3 = await asyncio.wait_for(
                            _fetch_search_html_with_retries(self, u3, pid),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_by_skills portal=%s fallback(location) timeout", pid)
                        h3, b3 = None, None
                    if h3 and b3:
                        job_urls = _sanitize_linkedin_job_listing_urls(
                            adapter.parse_job_links(h3, b3)
                        )
                        effective_html = h3
                if not job_urls:
                    u4 = adapter.build_search_url(
                        fb_terms,
                        max_results=max_per_portal,
                        posted_within_hours=None,
                        location=None,
                        **_linkedin_serp_kwargs(),
                    )
                    try:
                        h4, b4 = await asyncio.wait_for(
                            _fetch_search_html_with_retries(self, u4, pid),
                            timeout=5.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("scrape_by_skills portal=%s fallback(global) timeout", pid)
                        h4, b4 = None, None
                    if h4 and b4:
                        job_urls = _sanitize_linkedin_job_listing_urls(
                            adapter.parse_job_links(h4, b4)
                        )
                        effective_html = h4
                if effective_html is None:
                    per_portal[pid]["error"] = "Search page fetch failed or blocked after retries"
                    errors.append(f"{pid}: search page unavailable or blocked")
                    continue

                job_urls = job_urls[:max_per_portal]
                per_portal[pid]["links_found"] = len(job_urls)
                logger.info("scraper scrape_by_skills portal=%s parsed_links=%d", pid, len(job_urls))

                for url in job_urls:
                    try:
                        was_cached = await self.is_cached(url)
                        try:
                            job, _skills = await asyncio.wait_for(
                                self.scrape_and_store(url, source=pid), timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning("scrape_by_skills detail timeout portal=%s url=%s", pid, url[:80])
                            continue
                        if job:
                            if was_cached:
                                per_portal[pid]["cached"] += 1
                                total_cached += 1
                            else:
                                per_portal[pid]["new"] += 1
                                total_new += 1
                    except Exception as exc:
                        logger.warning("scrape error url=%s: %s", url[:60], exc)
                        errors.append(f"{pid}: {url[:50]}… → {exc}")
            except Exception as exc:
                logger.warning("portal %s search failed: %s", pid, exc)
                per_portal[pid]["error"] = str(exc)
                errors.append(f"{pid}: {exc}")

        db_n = await self.count_jobs_total()
        scraped = total_new + total_cached
        lp = sum(p["links_found"] for p in per_portal.values())
        sh_reason = "success" if lp > 0 else "blocked"
        if scraped == 0:
            errors.append(
                f"scrape_by_skills: no jobs stored this run; {db_n} job row(s) in DB cache."
            )
            logger.warning("scraper scrape_by_skills empty run; db_jobs=%d", db_n)
        out = {
            "portals": per_portal,
            "total_new": total_new,
            "total_cached": total_cached,
            "errors": errors,
            "links_parsed_total": lp,
            "db_jobs_count": db_n,
            "scrape_health": {
                "links_found": lp,
                "is_degraded": lp == 0 or scraped == 0,
                "reason": sh_reason,
            },
        }
        await set_cached_search(cache_key, result=out, source="scrape")
        return out

    # ── n8n / search-page helper (unchanged interface) ────────────────────────

    def _parse_job_links_from_page(self, html: str, base_url: str) -> list[str]:
        """Parse LinkedIn job links from a search-results page (used by scrape_search_page)."""
        from app.services.portals.linkedin import LinkedInAdapter

        return _sanitize_linkedin_job_listing_urls(
            LinkedInAdapter().parse_job_links(html, base_url)
        )

    def _source_from_url(self, url: str) -> str:
        return "linkedin" if "linkedin.com" in url.lower() else "imported"

    async def scrape_search_page(self, search_url: str, *, max_jobs: int = 30) -> dict:
        """
        Scrape a LinkedIn search URL (e.g. built by n8n).
        Interface unchanged; internally uses _fetch_with_retry now.
        """
        logger.info("scraper scrape_search_page url=%s", search_url[:200])
        html, base_url = await _fetch_search_html_with_retries(self, search_url, "search_page")
        if not html or not base_url:
            return {"new": 0, "cached": 0, "links_found": 0, "errors": ["Fetch failed or blocked after retries"]}

        job_urls = self._parse_job_links_from_page(html, base_url)[:max_jobs]
        logger.info("scraper scrape_search_page parsed_links=%d", len(job_urls))
        new_count = cached_count = 0
        errors: list[str] = []

        for url in job_urls:
            try:
                was_cached = await self.is_cached(url)
                source = self._source_from_url(url)
                job, _skills = await self.scrape_and_store(url, source=source)
                if job:
                    if was_cached:
                        cached_count += 1
                    else:
                        new_count += 1
            except Exception as exc:
                logger.warning("scrape_search_page error url=%s: %s", url[:50], exc)
                errors.append(f"{url[:60]}… → {exc}")

        return {"new": new_count, "cached": cached_count, "links_found": len(job_urls), "errors": errors}
