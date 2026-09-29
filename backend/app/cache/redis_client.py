"""
Async Redis connection pool with graceful degradation.

All callers use cache_get / cache_set — they never touch the raw Redis client.
When Redis is unavailable (not configured, or connection refused), every
function silently no-ops so the rest of the application works without Redis.

Exported:
  init_redis()  — call once at app startup
  close_redis() — call once at app shutdown
  get_redis()   → redis.asyncio.Redis | None
  cache_get(key) → bytes | None
  cache_set(key, value, ttl_seconds)
  cache_delete(key)
"""
import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    """
    Create the connection pool. Silently skips when REDIS_URL is empty.
    Called once from FastAPI lifespan and ARQ worker startup.
    """
    global _redis_pool
    settings = get_settings()
    if not settings.redis_url:
        logger.info("Redis disabled (REDIS_URL is empty)")
        return
    try:
        pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=False,   # raw bytes for embedding vectors
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
            max_connections=20,
        )
        await pool.ping()
        _redis_pool = pool
        logger.info("Redis connected: %s", settings.redis_url)
    except (RedisError, OSError, Exception) as exc:
        logger.info("Redis not available (%s) — continuing without cache", exc)
        _redis_pool = None


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
        except Exception:
            pass
        _redis_pool = None
        logger.info("Redis connection closed")


def get_redis() -> Optional[aioredis.Redis]:
    """Return the active Redis client, or None if unavailable."""
    return _redis_pool


async def cache_get(key: str) -> Optional[bytes]:
    """
    Fetch raw bytes from Redis.
    Returns None on cache miss, connection error, or when Redis is disabled.
    Never raises.
    """
    r = get_redis()
    if r is None:
        return None
    try:
        return await r.get(key)
    except (RedisError, Exception) as exc:
        logger.debug("cache_get(%s) error: %s", key, exc)
        return None


async def cache_set(key: str, value: bytes, ttl_seconds: int = 86400) -> None:
    """
    Store raw bytes with a TTL (default 24 h). Silently swallows all errors.
    """
    r = get_redis()
    if r is None:
        return
    try:
        await r.set(key, value, ex=ttl_seconds)
    except (RedisError, Exception) as exc:
        logger.debug("cache_set(%s) error: %s", key, exc)


async def cache_delete(key: str) -> None:
    """Delete a key. No-op when Redis is disabled."""
    r = get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except (RedisError, Exception) as exc:
        logger.debug("cache_delete(%s) error: %s", key, exc)
