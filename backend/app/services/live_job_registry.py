"""
Ephemeral scraped jobs — not stored in PostgreSQL.

Used when persist_scraped_jobs=False: listings live only in process memory so gap/match
use live HTML-derived data. IDs are synthetic (>= EPHEMERAL_JOB_ID_MIN) to avoid clashes
with DB-backed Job.id rows.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.services.live_resume_registry import EPHEMERAL_RESUME_ID_MIN

# Synthetic job ids for non-persisted scrapes (real DB ids are typically much lower).
# Range is [EPHEMERAL_JOB_ID_MIN, EPHEMERAL_RESUME_ID_MIN) so it does not overlap
# in-memory resume ids (>= EPHEMERAL_RESUME_ID_MIN).
EPHEMERAL_JOB_ID_MIN = 1_000_000_000

_jobs: dict[int, dict[str, Any]] = {}
_next_id = EPHEMERAL_JOB_ID_MIN
# URL snapshot cache (dedup window) — external_id -> (expiry_epoch, payload dict)
_url_snapshots: dict[str, tuple[float, dict[str, Any]]] = {}


def _ttl_seconds() -> float:
    return float(get_settings().scraper_cache_days * 86400)


def snapshot_get(external_id: str) -> dict[str, Any] | None:
    if external_id not in _url_snapshots:
        return None
    exp, payload = _url_snapshots[external_id]
    if time.time() > exp:
        del _url_snapshots[external_id]
        return None
    return payload


def snapshot_put(external_id: str, payload: dict[str, Any]) -> None:
    _url_snapshots[external_id] = (time.time() + _ttl_seconds(), payload)


def register_job(payload: dict[str, Any]) -> int:
    """Assign a synthetic id and store the job payload."""
    global _next_id
    jid = _next_id
    _next_id += 1
    row = dict(payload)
    row["id"] = jid
    _jobs[jid] = row
    return jid


def get_job(job_id: int) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    def _sort_key(d: dict[str, Any]) -> float:
        ts = d.get("fetched_at")
        if isinstance(ts, datetime):
            return ts.timestamp()
        return 0.0

    rows = sorted(_jobs.values(), key=_sort_key, reverse=True)
    return rows[:limit]


def count_live() -> int:
    return len(_jobs)


def list_jobs_as_gap_corpus(limit: int = 200) -> list[dict[str, Any]]:
    """
    Registry rows as gap/match corpus entries (title, skills, description snippet).
    Same shape as ScraperService.scrape_quick live_job_corpus items.
    """
    rows = list_jobs(limit)
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_sk = r.get("skill_names") or r.get("skills") or []
        skills = list(raw_sk) if isinstance(raw_sk, list) else []
        desc = str(r.get("description") or "")[:1200]
        out.append({
            "title": str(r.get("title") or ""),
            "skills": skills,
            "description": desc,
        })
    return out


def is_ephemeral_job_id(job_id: int) -> bool:
    return EPHEMERAL_JOB_ID_MIN <= job_id < EPHEMERAL_RESUME_ID_MIN


def clear_for_tests() -> None:
    global _next_id, _jobs, _url_snapshots
    _jobs = {}
    _url_snapshots = {}
    _next_id = EPHEMERAL_JOB_ID_MIN


def fetched_at_now() -> datetime:
    return datetime.now(timezone.utc)
