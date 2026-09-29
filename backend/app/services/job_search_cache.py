"""
1-hour cache for job search / scrape batches (keywords + location + window).
Reduces repeated LinkedIn hits and reuses last degraded (empty) results briefly.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

from app.cache.redis_client import cache_get, cache_set
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

REDIS_PREFIX = "jobsearch:v1:"
_MEM_MAX = 128
_memory_store: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def _ttl_seconds() -> int:
    return int(get_settings().job_search_cache_ttl_seconds)


def make_job_search_cache_key(
    *,
    skill_terms: list[str],
    location: str | None,
    posted_within_hours: int | None,
    mode: str,
    max_jobs_hint: int,
    portal_signature: str = "",
    linkedin_filter_signature: str = "",
) -> str:
    payload = {
        "terms": sorted({t.strip().lower() for t in skill_terms if t and t.strip()}),
        "loc": (location or "").strip().lower() or None,
        "hours": posted_within_hours,
        "mode": mode,
        "max": max_jobs_hint,
        "portals": portal_signature,
        "li_filters": linkedin_filter_signature or None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]
    return h


async def get_cached_search(cache_key: str) -> dict[str, Any] | None:
    """Return cached payload {result, remaining_urls?, timestamp, source} or None."""
    ttl = _ttl_seconds()
    rkey = REDIS_PREFIX + cache_key
    try:
        raw = await cache_get(rkey)
        if raw:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            data = json.loads(text)
            ts = float(data.get("timestamp", 0))
            if time.time() - ts <= ttl:
                logger.info("job_search_cache hit redis key=%s age_s=%.0f", cache_key[:12], time.time() - ts)
                return data
    except Exception as exc:
        logger.debug("job_search_cache redis read failed: %s", exc)

    now = time.time()
    if cache_key in _memory_store:
        ts, payload = _memory_store[cache_key]
        if now - ts <= ttl:
            _memory_store.move_to_end(cache_key)
            logger.info("job_search_cache hit memory key=%s age_s=%.0f", cache_key[:12], now - ts)
            return {**payload, "timestamp": ts}
        del _memory_store[cache_key]
    return None


async def set_cached_search(
    cache_key: str,
    *,
    result: dict[str, Any],
    remaining_urls: list[str] | None = None,
    source: str = "scrape",
) -> None:
    payload: dict[str, Any] = {
        "result": result,
        "timestamp": time.time(),
        "source": source,
    }
    if remaining_urls is not None:
        payload["remaining_urls"] = remaining_urls

    ttl = _ttl_seconds()
    rkey = REDIS_PREFIX + cache_key
    try:
        await cache_set(rkey, json.dumps(payload, separators=(",", ":")).encode("utf-8"), ttl_seconds=ttl)
    except Exception as exc:
        logger.debug("job_search_cache redis write failed: %s", exc)

    _memory_store[cache_key] = (payload["timestamp"], payload)
    _memory_store.move_to_end(cache_key)
    while len(_memory_store) > _MEM_MAX:
        _memory_store.popitem(last=False)

    logger.info(
        "job_search_cache store key=%s source=%s degraded=%s",
        cache_key[:12],
        source,
        result.get("market_scrape_degraded"),
    )
