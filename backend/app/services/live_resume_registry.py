"""
Ephemeral resumes — not stored in PostgreSQL.

Used when persist_resumes=False: PDF text and extracted skills live only in process
memory. IDs are synthetic (>= EPHEMERAL_RESUME_ID_MIN) to avoid clashing with DB rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

EPHEMERAL_RESUME_ID_MIN = 2_000_000_000

_next_id = EPHEMERAL_RESUME_ID_MIN
_resumes: dict[int, dict[str, Any]] = {}


def is_ephemeral_resume_id(resume_id: int) -> bool:
    return resume_id >= EPHEMERAL_RESUME_ID_MIN


def register_resume(
    *,
    filename: str,
    raw_text: str | None,
    candidate_name: str | None,
    skill_names: list[str],
    user_id: int | None,
    ai_summary: str | None = None,
) -> int:
    global _next_id
    rid = _next_id
    _next_id += 1
    _resumes[rid] = {
        "id": rid,
        "filename": filename,
        "raw_text": raw_text,
        "candidate_name": candidate_name,
        "skill_names": list(skill_names),
        "user_id": user_id,
        "ai_summary": ai_summary,
        "created_at": datetime.now(timezone.utc),
    }
    return rid


def get_resume(resume_id: int) -> dict[str, Any] | None:
    return _resumes.get(resume_id)


def update_resume(resume_id: int, **fields: Any) -> bool:
    row = _resumes.get(resume_id)
    if not row:
        return False
    row.update({k: v for k, v in fields.items() if v is not None or k in row})
    return True


def set_skill_names(resume_id: int, names: list[str]) -> bool:
    row = _resumes.get(resume_id)
    if not row:
        return False
    row["skill_names"] = list(names)
    return True


def list_resumes_for_user(user_id: int | None) -> list[dict[str, Any]]:
    """When user_id is None, return rows with no owner (anonymous uploads)."""
    rows = list(_resumes.values())
    if user_id is None:
        out = [r for r in rows if r.get("user_id") is None]
    else:
        out = [r for r in rows if r.get("user_id") == user_id]
    out.sort(key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def count_ephemeral() -> int:
    return len(_resumes)


def clear_for_tests() -> None:
    global _next_id, _resumes
    _resumes = {}
    _next_id = EPHEMERAL_RESUME_ID_MIN
