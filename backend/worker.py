"""
ARQ worker entry point.

Start the worker:
  uv run arq worker.WorkerSettings

Or with Docker:
  docker run ... arq worker.WorkerSettings

The worker:
- Picks up gap_analysis_task jobs enqueued by POST /analysis/resume-gap
- Runs prescrape_jobs as a cron every 6 hours (at 00:00, 06:00, 12:00, 18:00)
- Stores results in Redis (TTL = 1 hour); retrieved by GET /analysis/status/{task_id}
"""
from arq.cron import cron

from app.worker.settings import get_arq_redis_settings
from app.worker.tasks import (
    background_scrape_task,
    gap_analysis_task,
    prescrape_jobs,
    shutdown,
    startup,
)


class WorkerSettings:
    functions = [gap_analysis_task, prescrape_jobs, background_scrape_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_arq_redis_settings()
    cron_jobs = [
        # Every 6 hours: 00:00, 06:00, 12:00, 18:00
        cron(prescrape_jobs, hour={0, 6, 12, 18}, minute=0),
    ]
    max_jobs = 4            # limit concurrent jobs per worker instance
    job_timeout = 900       # scraping + embeddings + LLM
    keep_result = 3600      # keep task result in Redis for 1 hour
    queue_name = "arq:default"
