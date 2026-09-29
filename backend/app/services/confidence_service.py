"""Deterministic confidence labels for match/gap outputs (no black-box ML)."""
from __future__ import annotations

from typing import Literal

ConfidenceLabel = Literal["high", "medium", "low"]


def match_confidence(
    *,
    db_job_count: int,
    uncertainty_score: float,
    semantic_similarity: float,
    n_job_skills: int,
) -> ConfidenceLabel:
    """
    Combines corpus size, reference-skill sparsity, and embedding decisiveness.
    semantic_similarity distance from 0.5 proxies "how split" the text match is.
    """
    pts = 0
    if db_job_count >= 60:
        pts += 2
    elif db_job_count >= 25:
        pts += 1

    if uncertainty_score <= 10:
        pts += 2
    elif uncertainty_score <= 20:
        pts += 1

    if n_job_skills >= 8:
        pts += 1
    elif n_job_skills >= 4:
        pts += 0

    spread = abs(float(semantic_similarity) - 0.5)
    if spread >= 0.2:
        pts += 1
    elif spread >= 0.12:
        pts += 0

    if pts >= 5:
        return "high"
    if pts >= 3:
        return "medium"
    return "low"


def gap_confidence(*, jobs_count: int, market_skill_count: int, quality_band: str) -> ConfidenceLabel:
    if quality_band == "high" and jobs_count >= 40 and market_skill_count >= 30:
        return "high"
    if quality_band == "low" or jobs_count < 12:
        return "low"
    return "medium"
