"""
Career path suggestions from role graph + learned transition weights + market missing skills.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CareerTransitionStat
from app.services.match_service import MatchService
from app.services.normalization import normalize_role
from app.services.role_graph_service import next_roles_for


async def weighted_next_roles(session: AsyncSession, graph_key: str) -> tuple[list[str], list[dict]]:
    """
    Static graph edges get prior weight 1; CareerTransitionStat adds mass from aggregate user flows.
    Returns (ordered role labels, transition objects with probability).
    """
    gkey = (graph_key or "").strip().lower()
    if not gkey:
        gkey = "software engineer"
    static = next_roles_for(gkey)
    if not static:
        return [], []

    stmt = select(CareerTransitionStat).where(CareerTransitionStat.from_role == gkey)
    db_rows = (await session.execute(stmt)).scalars().all()
    db_map = {str(row.to_role).strip().lower(): int(row.weight) for row in db_rows}

    pairs: list[tuple[str, float]] = []
    static_norms: set[str] = set()
    for label in static:
        ln = normalize_role(label).strip().lower()
        static_norms.add(ln)
        obs = float(db_map.get(ln, 0))
        w = 1.0 + 0.22 * obs
        pairs.append((label, w))

    for to_r, wt in db_map.items():
        if to_r and to_r not in static_norms:
            display = to_r.title() if to_r.islower() else to_r
            pairs.append((display, 0.35 + 0.22 * float(wt)))

    total = sum(w for _, w in pairs) or 1.0
    pairs.sort(key=lambda x: -x[1])
    transitions = [{"role": r, "probability": round(w / total, 4)} for r, w in pairs[:15]]
    next_roles = [t["role"] for t in transitions]
    return next_roles, transitions


async def build_career_path(
    session: AsyncSession,
    *,
    resume_id: int,
    current_role: str | None,
) -> dict:
    """
    Returns current_role, next_roles (from weighted graph), transition probabilities,
    and required_skills toward the top suggested hop.
    """
    cr = normalize_role(current_role or "") or "software engineer"
    display_role = cr.title() if cr.islower() else cr
    graph_key = cr.strip().lower()
    nxt, transitions = await weighted_next_roles(session, graph_key)
    required: list[str] = []
    if nxt:
        ms = MatchService(session)
        gap = await ms.compute_resume_gap_for_role(resume_id, nxt[0])
        missing = gap.get("missing_skills") or []
        required = list(missing[:12])
    return {
        "current_role": display_role,
        "next_roles": nxt,
        "role_transitions": transitions,
        "required_skills": required,
    }
