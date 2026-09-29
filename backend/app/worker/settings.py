"""
ARQ WorkerSettings.

Imported by worker.py (the top-level arq entrypoint) and by app/main.py
(to create the ARQ enqueue pool at startup).

Usage:
  uv run arq worker.WorkerSettings
"""
import urllib.parse

from arq.connections import RedisSettings

from app.core.config import get_settings


def get_arq_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into the RedisSettings object ARQ expects."""
    url = get_settings().redis_url
    parsed = urllib.parse.urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
    )
