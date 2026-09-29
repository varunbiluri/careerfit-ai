"""
Embedding-based skill clustering: transitive groups via cosine similarity ≥ threshold.
Used to treat near-synonym skills as matched and to collapse duplicate gaps.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import get_settings
from app.services.embedding_service import get_embeddings_async

logger = logging.getLogger(__name__)


class _UnionFind:
    __slots__ = ("parent", "rank")

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _representatives(
    n: int,
    uf: _UnionFind,
    id_to_skill: list[str],
) -> dict[int, str]:
    """Map root id → lexicographically smallest skill name in component."""
    buckets: dict[int, list[str]] = defaultdict(list)
    for i in range(n):
        buckets[uf.find(i)].append(id_to_skill[i])
    return {root: min(names) for root, names in buckets.items()}


async def skill_to_canonical_map(
    skills: list[str],
    *,
    threshold: float | None = None,
) -> dict[str, str]:
    """
    Map each skill string to a canonical representative within its similarity cluster.
    Skills not in `skills` are not present in the map (caller should default to identity).
    """
    uniq = sorted({s.strip().lower() for s in skills if s and s.strip()})
    if not uniq:
        return {}
    settings = get_settings()
    max_u = getattr(settings, "skill_cluster_max_unique", 400)
    thr = threshold if threshold is not None else getattr(settings, "skill_cluster_similarity_threshold", 0.85)
    if len(uniq) > max_u:
        logger.debug("skill_cluster: %d unique skills exceeds max %d — identity map", len(uniq), max_u)
        return {s: s for s in uniq}

    embs = await get_embeddings_async(uniq)
    if len(embs) != len(uniq):
        logger.debug(
            "skill_cluster: embedding count mismatch (%s vs %s) — identity map",
            len(embs),
            len(uniq),
        )
        return {s: s for s in uniq}
    mat = np.asarray(embs, dtype=np.float64)
    sim = cosine_similarity(mat)
    n = len(uniq)
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if float(sim[i, j]) >= thr:
                uf.union(i, j)
    root_rep = _representatives(n, uf, uniq)
    out: dict[str, str] = {}
    for i, s in enumerate(uniq):
        out[s] = root_rep[uf.find(i)]
    return out


async def matched_missing_with_clusters(
    reference_names: list[str],
    candidate_names: list[str],
    *,
    threshold: float | None = None,
) -> tuple[list[str], list[str]]:
    """
    Same contract as match_service._matched_missing: reference = job/market required,
    candidate = resume skills. Returns (matched, missing) as lowercase normalized strings.
    """
    ref = [s.strip().lower() for s in reference_names if s and s.strip()]
    cand = [s.strip().lower() for s in candidate_names if s and s.strip()]
    ref_set, cand_set = set(ref), set(cand)
    exact = ref_set & cand_set
    if not ref_set:
        return [], []
    if not cand_set:
        return [], sorted(ref_set)

    union_skills = sorted(ref_set | cand_set)
    cmap = await skill_to_canonical_map(union_skills, threshold=threshold)
    cand_roots = {cmap.get(c, c) for c in cand_set}
    matched_set = {r for r in ref_set if cmap.get(r, r) in cand_roots}
    missing_set = ref_set - matched_set
    return sorted(matched_set), sorted(missing_set)


def collapse_skills_by_cluster(
    skill_names: list[str],
    canonical_map: dict[str, str],
    *,
    demand_key: dict[str, float] | None = None,
) -> list[str]:
    """
    Deduplicate skills that map to the same canonical; keep highest-demand representative
    when demand_key maps skill → weight (e.g. demand %).
    """
    if not skill_names:
        return []
    groups: dict[str, list[str]] = defaultdict(list)
    for s in skill_names:
        k = s.strip().lower()
        if not k:
            continue
        root = canonical_map.get(k, k)
        groups[root].append(k)
    out: list[str] = []
    for root, members in groups.items():
        if demand_key:
            best = max(members, key=lambda m: demand_key.get(m, 0.0))
            out.append(best)
        else:
            out.append(min(members))
    # Stable: sort by demand if provided else alpha
    if demand_key:
        out.sort(key=lambda x: (-demand_key.get(x, 0.0), x))
    else:
        out.sort()
    return out
