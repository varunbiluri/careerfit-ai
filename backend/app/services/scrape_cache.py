"""
Scrape caching helpers: freshness checks, distributed locking, and data-quality
computation.

Design
------
Freshness is tracked with a single Redis key per (skill_terms, location) pair:

  scrape:ts:{cache_key}   →  UNIX float timestamp of last completed scrape

Jobs are considered "fresh" when that timestamp is < scrape_freshness_hours ago.
This lets multiple API workers share a single freshness signal without any DB
query on the hot path.

Distributed lock (thundering-herd prevention):

  scrape:lock:{cache_key} →  SET NX with TTL

When two gap analysis requests arrive for the same skills at the same time, only
the first one gets the lock and performs the scrape.  The second one detects the
lock, skips scraping, and returns whatever is already in the DB.

Data quality:

  compute_data_quality() queries the jobs table and returns the DataQualityMeta
  schema (jobs_count, freshness_hours, completeness_score, is_fresh, scraped_at).
"""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Job

logger = get_logger(__name__)

# ── Redis key prefixes ────────────────────────────────────────────────────────
_LOCK_PREFIX = "scrape:lock:"
_TS_PREFIX   = "scrape:ts:"

# ── TTL constants ─────────────────────────────────────────────────────────────
SCRAPE_LOCK_TTL = 600    # 10 min — safety valve if worker crashes before release
SCRAPE_TS_TTL   = 86400  # 24 h  — how long to remember last-scrape timestamp


# ── Key generation ────────────────────────────────────────────────────────────

def make_scrape_key(skill_terms: list[str], location: str, role_context: str = "") -> str:
    """
    Deterministic 16-char hex key for a (skills, location, optional target role) tuple.
    Sorted so ["Python", "AWS"] and ["AWS", "Python"] produce the same key.
    """
    normalised = "|".join(sorted(t.strip().lower() for t in skill_terms if t.strip()))
    normalised += ":" + location.strip().lower()
    if role_context.strip():
        normalised += ":" + role_context.strip().lower()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


# ── Freshness helpers ─────────────────────────────────────────────────────────

async def get_last_scrape_time(cache_key: str) -> datetime | None:
    """Return UTC datetime of the last completed scrape, or None if unknown."""
    from app.cache.redis_client import cache_get
    raw = await cache_get(f"{_TS_PREFIX}{cache_key}")
    if raw is None:
        return None
    try:
        ts = float(raw.decode())
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


async def record_scrape_time(cache_key: str) -> None:
    """Write the current UTC timestamp as the last-scrape time for this key."""
    from app.cache.redis_client import cache_set
    ts = datetime.now(timezone.utc).timestamp()
    await cache_set(f"{_TS_PREFIX}{cache_key}", str(ts).encode(), ttl_seconds=SCRAPE_TS_TTL)


def is_fresh(last_scrape: datetime | None, max_age_hours: float = 6.0) -> bool:
    """Return True when last_scrape happened within max_age_hours."""
    if last_scrape is None:
        return False
    age_hours = (datetime.now(timezone.utc) - last_scrape).total_seconds() / 3600
    return age_hours < max_age_hours


# ── Distributed lock ──────────────────────────────────────────────────────────

async def try_acquire_scrape_lock(cache_key: str, ttl: int = SCRAPE_LOCK_TTL) -> bool:
    """
    Attempt a Redis SET NX (set-if-not-exists) with TTL.
    Returns True  → this caller holds the lock and should proceed with scraping.
    Returns False → another worker is already scraping; skip scraping this request.
    Falls back to True (always proceed) when Redis is unavailable.
    """
    from app.cache.redis_client import get_redis
    r = get_redis()
    if r is None:
        return True  # no Redis — can't coordinate, proceed
    try:
        result = await r.set(f"{_LOCK_PREFIX}{cache_key}", "1", ex=ttl, nx=True)
        acquired = result is not None
        if acquired:
            logger.debug("scrape lock acquired key=%s", cache_key)
        else:
            logger.debug("scrape lock busy key=%s — skipping scrape", cache_key)
        return acquired
    except Exception as exc:
        logger.debug("scrape lock acquire error (%s) — proceeding unlocked", exc)
        return True


async def release_scrape_lock(cache_key: str) -> None:
    """
    Release the scrape lock.  Always call this in a finally block after scraping
    so the lock doesn't stay set until its TTL expires on normal exits.
    """
    from app.cache.redis_client import cache_delete
    await cache_delete(f"{_LOCK_PREFIX}{cache_key}")
    logger.debug("scrape lock released key=%s", cache_key)


# ── Data quality ──────────────────────────────────────────────────────────────

def _quality_band_for(
    jobs_count: int,
    *,
    synthetic_fallback_used: bool,
    scrape_degraded: bool,
    scrape_reason: str | None,
    demand_source: str = "real",
) -> str:
    if synthetic_fallback_used:
        return "low"
    if jobs_count == 0:
        return "low"
    if demand_source == "synthetic":
        return "low"
    # Large curated corpus without live scrape is still usable → medium, not low
    if demand_source == "corpus" and jobs_count >= 50:
        if scrape_degraded and jobs_count < 80:
            return "medium"
        return "high" if jobs_count >= 120 else "medium"
    if scrape_degraded and jobs_count < 20 and scrape_reason in ("blocked", "empty", None):
        return "low"
    if jobs_count > 50:
        return "high"
    if jobs_count < 20:
        return "medium"
    return "medium"


async def compute_data_quality(
    session: AsyncSession,
    last_scrape: datetime | None,
    max_age_hours: float = 6.0,
    source: str = "unknown",
    *,
    synthetic_fallback_used: bool = False,
    scrape_degraded: bool = False,
    scrape_health_reason: str | None = None,
    demand_source: str | None = None,
    live_jobs_count: int | None = None,
) -> "DataQualityMeta":
    """
    Compute data-quality metadata from the jobs table.

    completeness_score = fraction of jobs that have a non-null title, a
    description longer than 50 chars, AND a company name.  Values near 1.0
    mean the scraper returned clean, usable data; values near 0.0 indicate
    mostly empty or login-wall pages.

    When ``live_jobs_count`` is set and the DB has zero Job rows, metadata
    reflects in-memory scraped listings (live_market_only mode).
    """
    from app.schemas.match import DataQualityMeta
    from app.services.job_corpus_service import infer_demand_source

    total = int((await session.execute(select(func.count(Job.id)))).scalar() or 0)
    ds: str = demand_source if demand_source is not None else await infer_demand_source(session)

    if total == 0 and live_jobs_count is not None and live_jobs_count > 0:
        freshness_hours = 999.0
        if last_scrape is not None:
            freshness_hours = round(
                (datetime.now(timezone.utc) - last_scrape).total_seconds() / 3600, 2
            )
        return DataQualityMeta(
            jobs_count=live_jobs_count,
            freshness_hours=freshness_hours,
            completeness_score=0.65,
            is_fresh=freshness_hours < max_age_hours,
            scraped_at=last_scrape,
            source=source,
            quality_band=_quality_band_for(
                live_jobs_count,
                synthetic_fallback_used=synthetic_fallback_used,
                scrape_degraded=scrape_degraded,
                scrape_reason=scrape_health_reason,
                demand_source="real",
            ),
            demand_source="real",
        )

    if total == 0:
        return DataQualityMeta(
            jobs_count=0,
            freshness_hours=999.0,
            completeness_score=0.0,
            is_fresh=False,
            scraped_at=None,
            source=source,
            quality_band=_quality_band_for(
                0,
                synthetic_fallback_used=synthetic_fallback_used,
                scrape_degraded=scrape_degraded,
                scrape_reason=scrape_health_reason,
                demand_source=ds,
            ),
            demand_source=ds,  # type: ignore[arg-type]
        )

    # Count jobs that pass the basic completeness bar
    complete_stmt = select(func.count(Job.id)).where(
        Job.title.isnot(None),
        Job.description.isnot(None),
        func.length(Job.description) > 50,
        Job.company.isnot(None),
    )
    complete_count = (await session.execute(complete_stmt)).scalar() or 0

    freshness_hours = 999.0
    if last_scrape is not None:
        freshness_hours = round(
            (datetime.now(timezone.utc) - last_scrape).total_seconds() / 3600, 2
        )

    return DataQualityMeta(
        jobs_count=total,
        freshness_hours=freshness_hours,
        completeness_score=round(complete_count / total, 3) if total else 0.0,
        is_fresh=freshness_hours < max_age_hours,
        scraped_at=last_scrape,
        source=source,
        quality_band=_quality_band_for(
            total,
            synthetic_fallback_used=synthetic_fallback_used,
            scrape_degraded=scrape_degraded,
            scrape_reason=scrape_health_reason,
            demand_source=ds,
        ),
        demand_source=ds,  # type: ignore[arg-type]
    )
