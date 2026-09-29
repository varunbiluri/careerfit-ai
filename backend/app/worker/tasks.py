"""
ARQ background task definitions.

Each task receives a ctx dict as its first argument (ARQ convention).
ctx["session_factory"] is injected during startup().

Tasks run in a separate worker process with their own event loop and DB
connections, so they must never share SQLAlchemy sessions with the API process.
"""
import logging
import traceback
from typing import Any

from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------

async def startup(ctx: dict) -> None:
    """
    Called once when the ARQ worker process starts.
    Initialises logging, DB session factory, Redis embedding cache, and ARQ pool
    (so tasks can enqueue follow-up jobs such as background_scrape_task).
    """
    setup_logging()
    from app.db.session import async_session_maker
    from app.cache.redis_client import init_redis
    from app.worker.settings import get_arq_redis_settings
    from arq import create_pool

    ctx["session_factory"] = async_session_maker
    await init_redis()
    # Expose an ARQ pool so tasks can enqueue follow-up jobs without importing
    # the app-level pool from main.py (which lives in a different process).
    try:
        ctx["arq_pool"] = await create_pool(get_arq_redis_settings())
    except Exception as exc:
        logger.warning("ARQ worker: could not create arq_pool (%s) — background tasks disabled", exc)
        ctx["arq_pool"] = None
    logger.info("ARQ worker startup complete")


async def shutdown(ctx: dict) -> None:
    """Called once when the worker process is stopping."""
    from app.cache.redis_client import close_redis
    await close_redis()
    if ctx.get("arq_pool") is not None:
        await ctx["arq_pool"].close()
    logger.info("ARQ worker shutdown complete")


# ---------------------------------------------------------------------------
# Task: gap analysis
# ---------------------------------------------------------------------------

async def gap_analysis_task(
    ctx: dict,
    resume_id: int,
    target_role: str | None = None,
    experience_input: str | None = None,
) -> dict[str, Any]:
    """
    Full resume gap analysis in a background worker.

    Enqueued by POST /analysis/resume-gap when Redis/ARQ is available.
    The return dict is stored by ARQ in Redis and retrieved via
    GET /analysis/status/{task_id}.

    Return shape:
      {"status": "completed", "result": <ResumeGapOut as dict>}
      {"status": "failed",    "error":  "<message>"}
    """
    logger.info("gap_analysis_task start resume_id=%d", resume_id)
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        try:
            from app.services.gap_service import GapAnalysisService
            result = await GapAnalysisService(session, arq_pool=ctx.get("arq_pool")).analyze(
                resume_id,
                target_role=target_role,
                experience_input=experience_input,
            )
            logger.info("gap_analysis_task done resume_id=%d", resume_id)
            return {"status": "completed", "result": result.model_dump(mode="json")}
        except ValueError as exc:
            logger.warning("gap_analysis_task resume_id=%d ValueError: %s", resume_id, exc)
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:
            logger.error(
                "gap_analysis_task resume_id=%d unexpected error:\n%s",
                resume_id,
                traceback.format_exc(),
            )
            return {"status": "failed", "error": f"Internal error: {exc}"}


# ---------------------------------------------------------------------------
# Task: pre-scrape jobs (also used as cron)
# ---------------------------------------------------------------------------

async def prescrape_jobs(ctx: dict) -> dict[str, Any]:
    """
    Proactively scrape top-demand jobs every 6 hours via cron.

    Keeps the DB warm so gap analysis requests skip the scraping step
    (scraper returns cached results instead of hitting LinkedIn live).
    """
    logger.info("prescrape_jobs start")
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        try:
            from app.services.skill_service import skill_demand_percentages
            from app.services.scraper_service import ScraperService

            # Drive search terms from top-demand skills already in DB
            demand = await skill_demand_percentages(session)
            top_skills = [s.name for s, _c, _p in demand[:20] if s.name]
            if not top_skills:
                # No demand data yet — use a sensible bootstrap list
                top_skills = [
                    "machine learning", "data science", "python", "deep learning",
                    "NLP", "MLOps", "cloud computing", "data engineering",
                    "PyTorch", "TensorFlow",
                ]

            # Use config for location/time-window — previously hardcoded "India"/24h
            from app.core.config import get_settings
            settings = get_settings()
            scraper = ScraperService(session)
            result = await scraper.scrape_by_skills(
                top_skills,
                portal_ids=None,
                max_per_portal=10,
                posted_within_hours=settings.scraper_default_time_window_hours,
                location=settings.scraper_default_location,
            )
            await session.commit()
            logger.info(
                "prescrape_jobs done new=%d cached=%d errors=%s",
                result.get("total_new", 0),
                result.get("total_cached", 0),
                result.get("errors", []),
            )
            return {"status": "completed", **result}
        except Exception as exc:
            logger.error("prescrape_jobs failed: %s\n%s", exc, traceback.format_exc())
            return {"status": "failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Task: background scrape (enqueued by GapAnalysisService after quick batch)
# ---------------------------------------------------------------------------

async def background_scrape_task(
    ctx: dict,
    skill_terms: list[str],
    job_urls: list[str],
    location: str,
    cache_key: str,
) -> dict[str, Any]:
    """
    Scrape the remaining job URLs that were not processed in the quick batch.

    Enqueued by GapAnalysisService after scrape_quick() returns the non-quick
    remainder.  Releases the scrape lock and records the completed scrape time
    so subsequent requests see fresh data immediately.

    Args:
        skill_terms: original search terms (used only for logging).
        job_urls:    URLs to scrape in this task.
        location:    target location (logged for observability).
        cache_key:   Redis key used by the scrape-freshness and lock helpers.
    """
    logger.info(
        "background_scrape_task start urls=%d location=%s cache_key=%s",
        len(job_urls),
        location,
        cache_key,
    )
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        try:
            from app.services.scraper_service import ScraperService
            from app.services.scrape_cache import record_scrape_time, release_scrape_lock

            scraper = ScraperService(session)
            result = await scraper.scrape_urls(job_urls, source="linkedin")
            await session.commit()

            await record_scrape_time(cache_key)
            logger.info(
                "background_scrape_task done new=%d cached=%d errors=%s",
                result.get("total_new", 0),
                result.get("total_cached", 0),
                result.get("errors", []),
            )
            return {"status": "completed", **result}
        except Exception as exc:
            logger.error(
                "background_scrape_task failed cache_key=%s:\n%s",
                cache_key,
                traceback.format_exc(),
            )
            return {"status": "failed", "error": str(exc)}
        finally:
            # Always release the lock so the next gap analysis isn't blocked
            # waiting for the TTL to expire.
            try:
                from app.services.scrape_cache import release_scrape_lock
                await release_scrape_lock(cache_key)
            except Exception as rel_exc:
                logger.warning("background_scrape_task: lock release failed: %s", rel_exc)
