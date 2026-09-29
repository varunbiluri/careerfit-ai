"""
CareerFit AI — FastAPI backend. API only; frontend is separate.

Production additions (beyond dev baseline):
  - RequestTimingMiddleware  — structured request duration logs
  - slowapi rate limiting    — per-IP limits on upload and gap analysis
  - Redis cache              — L2 embedding cache + ARQ task queue
  - ARQ background jobs      — gap analysis runs in worker process
  - JWT authentication       — /auth/register, /auth/login, /auth/me
  - Prometheus metrics       — /metrics endpoint (prometheus_fastapi_instrumentator)
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.cache.redis_client import close_redis, init_redis
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import get_logger, setup_logging
from app.db import init_db
from app.models import (  # noqa: F401 — register models with SQLAlchemy
    CareerProgress,
    CareerTransitionStat,
    Job,
    Resume,
    Skill,
    User,
    UserFeedback,
    UserProfile,
)
from app.routers import jobs, scraper
from app.routers import resume as resume_router
from app.routers import analysis
from app.routers.auth import router as auth_router
from app.routers.log_viewer import router as log_viewer_router

logger = get_logger(__name__)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log method, path, HTTP status and wall-clock duration for every request."""
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "request method=%s path=%s status=%d duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - t0) * 1000,
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()

    # Warn on default JWT secret so developers don't ship insecure keys.
    if "change-me" in settings.jwt_secret_key and not settings.debug:
        logger.warning(
            "JWT_SECRET_KEY is set to the default placeholder. "
            "Set a strong random value (openssl rand -hex 32) before production deployment."
        )

    # Database
    try:
        await init_db()
        logger.info("Database connected and tables ready")
        # Seed curated job corpus when the DB is sparse (scraper-independent market).
        try:
            from app.db.session import async_session_maker
            from app.services.job_corpus_service import seed_corpus_if_needed
            from app.services.skill_service import invalidate_skill_demand_caches

            async with async_session_maker() as corp_session:
                added = await seed_corpus_if_needed(corp_session)
                if added:
                    await corp_session.commit()
                    await invalidate_skill_demand_caches()
                    logger.info("Startup: seeded %d job(s) from job_corpus.json", added)
        except Exception as corp_exc:
            logger.warning("Startup job corpus seed skipped: %s", corp_exc)
    except Exception as exc:
        logger.warning("Database unavailable at startup: %s", exc)

    # Redis (graceful degradation — logs if unavailable)
    await init_redis()

    # ARQ only when Redis is actually connected — avoids arq.connections retry spam when Redis is down
    from app.cache.redis_client import get_redis

    if get_redis() is None:
        app.state.arq_pool = None
        logger.info(
            "ARQ disabled — Redis not connected (gap analysis runs in-process; no embedding L2 cache). "
            "Set REDIS_URL and run Redis to enable background jobs + cache."
        )
    else:
        try:
            from arq import create_pool
            from app.worker.settings import get_arq_redis_settings

            app.state.arq_pool = await create_pool(get_arq_redis_settings())
            logger.info("ARQ pool created — background jobs enabled")
        except Exception as exc:
            app.state.arq_pool = None
            logger.warning("ARQ pool unavailable (%s) — gap analysis will run synchronously", exc)

    if settings.log_viewer_enabled:
        if not settings.log_viewer_token:
            logger.warning(
                "LOG_VIEWER_ENABLED is set but LOG_VIEWER_TOKEN is empty — /logs/recent stays disabled"
            )
        elif not settings.log_file_path:
            logger.warning(
                "LOG_VIEWER_ENABLED is set but LOG_FILE_PATH is empty — log viewer will return 503"
            )

    logger.info("Application started")
    yield

    # Shutdown
    if getattr(app.state, "arq_pool", None) is not None:
        try:
            await app.state.arq_pool.aclose()
        except Exception:
            pass
    await close_redis()
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="CareerFit AI — Resume skill gap and job match API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # --- Rate limiting ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # --- Prometheus metrics at /metrics ---
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # --- Middleware (added last-in = outermost wrapper) ---
    app.add_middleware(RequestTimingMiddleware)
    # CORS: allow_origins=["*"] with allow_credentials=True is rejected by all
    # modern browsers (CORS spec §3.2.2). Use explicit origins from settings.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ---
    app.include_router(auth_router)
    app.include_router(jobs.router)
    app.include_router(resume_router.router)
    app.include_router(analysis.router)
    app.include_router(scraper.router)
    # /logs/* — matches dev Vite proxy (strips /api) and nginx that forwards without /api prefix.
    app.include_router(log_viewer_router)
    # /api/logs/* — same routes when reverse proxy forwards full path /api/... to uvicorn.
    app.include_router(log_viewer_router, prefix="/api")

    @app.get("/health", tags=["ops"])
    def health():
        """Liveness probe. Also reports Redis and ARQ availability."""
        from app.cache.redis_client import get_redis
        return {
            "status": "ok",
            "redis": "connected" if get_redis() is not None else "disabled",
            "arq": "connected" if getattr(app.state, "arq_pool", None) is not None else "disabled",
        }

    return app


app = create_app()
