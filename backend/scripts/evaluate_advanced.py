"""
evaluate_advanced.py — Complete evaluation pipeline for resume–job matching.

Compares three scoring approaches:
  1. TF-IDF      — sklearn TfidfVectorizer + cosine similarity (text baseline)
  2. Embedding   — BGE embeddings + cosine similarity only (no skill/demand features)
  3. Production  — 0.5·S + 0.3·O + 0.2·K − 0.2·D  (your full model)

Ground truth: binary relevance — a (resume, job) pair is RELEVANT when
    |resume_skills ∩ job_skills| / |job_skills| ≥ 30%

Metrics: Precision@K, Recall@K, NDCG@K (log2 discount), MRR  for K ∈ {1, 3, 5, 10}

Usage (from backend/):
    python3 -m scripts.evaluate_advanced --synthetic
    python3 -m scripts.evaluate_advanced --synthetic --limit 20
    python3 -m scripts.evaluate_advanced --synthetic --output-csv results/eval_adv.csv --plot
    python3 -m scripts.evaluate_advanced                  # loads real DB data
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path: ensure backend/ is importable regardless of CWD
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as _cosine

# Production scoring weights — imported directly to stay in sync
from app.services.match_service import (
    WEIGHT_DEMAND_PENALTY,
    WEIGHT_KEYWORD,
    WEIGHT_SEMANTIC,
    WEIGHT_SKILL_OVERLAP,
)

_SKILLS_PATH = _BACKEND / "data" / "skills_dictionary.json"
_RELEVANCE_THRESHOLD = 0.30   # 30% skill overlap → relevant
_RANDOM_SEED = 42


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class ResumeRecord:
    id: int
    raw_text: str
    skill_names: list[str]


@dataclass
class JobRecord:
    id: int
    title: str
    description: str
    skill_names: list[str]


# ============================================================================
# Data loading
# ============================================================================

def _all_skills_from_dict() -> list[str]:
    """Return a flat list of all skills from skills_dictionary.json."""
    if not _SKILLS_PATH.exists():
        # Hard-coded fallback so --synthetic works without the data file
        return [
            "Python", "R", "SQL", "Java", "Scala", "C++",
            "TensorFlow", "PyTorch", "Keras", "scikit-learn", "XGBoost",
            "BERT", "Transformers", "spaCy", "NLTK",
            "OpenCV", "YOLO",
            "Docker", "Kubernetes", "MLflow", "Airflow", "Git",
            "AWS", "GCP", "Azure",
            "Spark", "Kafka", "dbt", "Snowflake", "BigQuery",
            "Bayesian", "A/B Testing", "Statistics",
            "Tableau", "Power BI", "Jupyter",
        ]
    with open(_SKILLS_PATH, encoding="utf-8") as f:
        data: dict[str, list[str]] = json.load(f)
    return [s for bucket in data.values() for s in bucket if s and isinstance(s, str)]


def generate_synthetic_data(
    n_resumes: int = 20,
    n_jobs: int = 50,
    seed: int = _RANDOM_SEED,
) -> tuple[list[ResumeRecord], list[JobRecord], dict[str, float]]:
    """
    Build a deterministic synthetic dataset from skills_dictionary.json.

    Resumes and jobs share the same skill pool with different random subsets,
    ensuring a spread of overlap values for a meaningful retrieval benchmark.
    Demand data is random uniform [5, 80] per skill.
    """
    rng = np.random.default_rng(seed)
    all_skills = _all_skills_from_dict()
    n_s = len(all_skills)

    resumes: list[ResumeRecord] = []
    for i in range(n_resumes):
        k = int(rng.integers(6, min(22, n_s)))
        skills = list(rng.choice(all_skills, size=k, replace=False))
        text = (
            f"Software engineer experienced with {', '.join(skills[:5])}. "
            f"Proficient in {', '.join(skills[5:10])} and data-driven development. "
            "Background in machine learning, system design, and distributed computing."
        )
        resumes.append(ResumeRecord(id=i, raw_text=text, skill_names=skills))

    jobs: list[JobRecord] = []
    titles = [
        "ML Engineer", "Data Scientist", "Backend Engineer", "MLOps Engineer",
        "Data Engineer", "AI Researcher", "Applied Scientist",
    ]
    for i in range(n_jobs):
        k = int(rng.integers(4, min(16, n_s)))
        skills = list(rng.choice(all_skills, size=k, replace=False))
        title = str(rng.choice(titles))
        desc = (
            f"We are looking for a {title} with expertise in {', '.join(skills[:4])}. "
            f"Experience with {', '.join(skills[4:8]) if len(skills) > 4 else 'cloud platforms'} "
            "is a plus. Responsibilities: model training, deployment, and monitoring."
        )
        jobs.append(JobRecord(id=i, title=title, description=desc, skill_names=skills))

    demand_data: dict[str, float] = {
        s: float(rng.uniform(5.0, 80.0)) for s in all_skills
    }
    return resumes, jobs, demand_data


async def _load_from_db(limit: Optional[int]) -> tuple[list[ResumeRecord], list[JobRecord], dict[str, float]]:
    """Query resumes, jobs, and demand percentages from Postgres."""
    from sqlalchemy import select
    from app.db.session import async_session_maker
    from app.models import Job, JobSkill, Resume, ResumeSkill, Skill
    from app.services.skill_service import skill_demand_percentages

    async with async_session_maker() as session:
        # Resumes
        r_stmt = select(Resume).order_by(Resume.id.desc())
        if limit:
            r_stmt = r_stmt.limit(limit)
        resumes_orm = (await session.execute(r_stmt)).scalars().all()

        resumes: list[ResumeRecord] = []
        for r in resumes_orm:
            s_stmt = (
                select(Skill.name)
                .join(ResumeSkill, ResumeSkill.skill_id == Skill.id)
                .where(ResumeSkill.resume_id == r.id)
            )
            skills = list((await session.execute(s_stmt)).scalars().all())
            resumes.append(ResumeRecord(
                id=r.id,
                raw_text=(r.raw_text or "").strip(),
                skill_names=skills,
            ))

        # Jobs (cap at 200 for tractable evaluation)
        j_stmt = select(Job).order_by(Job.id.desc()).limit(200)
        jobs_orm = (await session.execute(j_stmt)).scalars().all()

        jobs: list[JobRecord] = []
        for j in jobs_orm:
            s_stmt = (
                select(Skill.name)
                .join(JobSkill, JobSkill.skill_id == Skill.id)
                .where(JobSkill.job_id == j.id)
            )
            skills = list((await session.execute(s_stmt)).scalars().all())
            jobs.append(JobRecord(
                id=j.id,
                title=(j.title or "").strip(),
                description=(j.description or "").strip(),
                skill_names=skills,
            ))

        # Demand
        demand_rows = await skill_demand_percentages(session)
        demand_data: dict[str, float] = {s.name: float(pct) for s, _c, pct in demand_rows}

    return resumes, jobs, demand_data


async def load_data(
    synthetic: bool,
    limit: Optional[int],
) -> tuple[list[ResumeRecord], list[JobRecord], dict[str, float]]:
    """
    Load data from DB or generate synthetic fallback.
    Automatically falls back to synthetic when DB is empty or unreachable.
    """
    if synthetic:
        print("[data]  Using synthetic data  (--synthetic)")
        r, j, d = generate_synthetic_data(n_resumes=limit or 20, n_jobs=50)
        print(f"        {len(r)} resumes, {len(j)} jobs")
        return r, j, d

    print("[data]  Loading from database …", end="", flush=True)
    try:
        r, j, d = await _load_from_db(limit=limit)
        if r and j:
            print(f" {len(r)} resumes, {len(j)} jobs")
            return r, j, d
        print(" DB empty — falling back to synthetic data")
    except Exception as exc:
        print(f" unavailable ({exc}) — falling back to synthetic data")

    r, j, d = generate_synthetic_data(n_resumes=limit or 20, n_jobs=50)
    print(f"        {len(r)} resumes, {len(j)} jobs (synthetic)")
    return r, j, d


# ============================================================================
# Embedding cache
# ============================================================================

async def build_embedding_cache(
    resumes: list[ResumeRecord],
    jobs: list[JobRecord],
) -> dict[str, list[float]]:
    """
    Batch-encode every unique resume/job text in one forward pass.
    Uses the existing embedding_service (BGE-small-en-v1.5) with its two-layer
    cache (in-process LRU + Redis L2). Falls back to empty dict on failure.
    """
    from app.services.embedding_service import get_embeddings_async

    unique_texts = list({
        *(r.raw_text for r in resumes if r.raw_text),
        *(j.description for j in jobs if j.description),
    })
    if not unique_texts:
        return {}

    print(f"[embed]  Encoding {len(unique_texts)} unique texts …", end="", flush=True)
    t0 = time.perf_counter()
    try:
        embeddings = await get_embeddings_async(unique_texts)
    except Exception as exc:
        print(f" FAILED ({exc}) — embedding model unavailable")
        return {}
    elapsed = time.perf_counter() - t0
    print(f" {elapsed:.2f}s  (dim={len(embeddings[0]) if embeddings else 'n/a'})")

    return dict(zip(unique_texts, embeddings))


# ============================================================================
# Ground truth
# ============================================================================

def compute_relevance(
    resumes: list[ResumeRecord],
    jobs: list[JobRecord],
    threshold: float = _RELEVANCE_THRESHOLD,
) -> dict[tuple[int, int], bool]:
    """
    Binary relevance for every (resume_idx, job_idx) pair.

    Definition: relevant iff  |resume_skills ∩ job_skills| / |job_skills| ≥ threshold

    Matching is case-insensitive and strip()-normalised.
    Jobs with no skills are always irrelevant.
    """
    relevance: dict[tuple[int, int], bool] = {}
    for i, resume in enumerate(resumes):
        r_set = {s.strip().lower() for s in resume.skill_names}
        for j, job in enumerate(jobs):
            j_set = {s.strip().lower() for s in job.skill_names}
            if j_set:
                overlap = len(r_set & j_set) / len(j_set)
                relevance[(i, j)] = overlap >= threshold
            else:
                relevance[(i, j)] = False
    return relevance


def _relevant_jobs_for_resume(
    resume_idx: int,
    n_jobs: int,
    relevance: dict[tuple[int, int], bool],
) -> set[int]:
    return {j for j in range(n_jobs) if relevance.get((resume_idx, j), False)}


# ============================================================================
# Scoring models
# ============================================================================

def score_tfidf(
    resumes: list[ResumeRecord],
    jobs: list[JobRecord],
) -> np.ndarray:
    """
    Baseline 1: TF-IDF cosine similarity.

    Fits the vectorizer on the combined corpus (resumes + jobs) so both share
    the same IDF weights. Returns a (n_resumes × n_jobs) matrix in [0, 1].
    """
    r_texts = [r.raw_text or " " for r in resumes]
    j_texts = [j.description or " " for j in jobs]

    vec = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
    )
    vec.fit(r_texts + j_texts)          # shared vocabulary
    r_mat = vec.transform(r_texts)
    j_mat = vec.transform(j_texts)

    return _cosine(r_mat, j_mat)        # (n_resumes, n_jobs)


def score_embedding_only(
    resumes: list[ResumeRecord],
    jobs: list[JobRecord],
    emb_cache: dict[str, list[float]],
) -> np.ndarray:
    """
    Baseline 2: BGE embedding cosine similarity (semantic signal only).

    No skill overlap, no keyword coverage, no demand penalty.
    Falls back to zero matrix when embeddings are unavailable.
    Returns (n_resumes × n_jobs) in [0, 1].
    """
    dim = next((len(v) for v in emb_cache.values()), 1)
    zero = [0.0] * dim

    r_embs = np.array([emb_cache.get(r.raw_text, zero) for r in resumes])
    j_embs = np.array([emb_cache.get(j.description, zero) for j in jobs])

    # Guard: all-zero rows produce NaN from cosine_similarity; convert to 0
    norms_r = np.linalg.norm(r_embs, axis=1, keepdims=True)
    norms_j = np.linalg.norm(j_embs, axis=1, keepdims=True)
    if np.any(norms_r == 0) or np.any(norms_j == 0):
        return np.zeros((len(resumes), len(jobs)))

    return _cosine(r_embs, j_embs)      # (n_resumes, n_jobs)


def score_production_model(
    resumes: list[ResumeRecord],
    jobs: list[JobRecord],
    emb_cache: dict[str, list[float]],
    demand_data: dict[str, float],
) -> np.ndarray:
    """
    Production model: Score = 0.5·S + 0.3·O + 0.2·K − 0.2·D  (clipped to [0, 100])

      S  = semantic cosine similarity × 100          (embedding_service)
      O  = skill overlap %  (|resume∩job| / |job|)   (exact, case-insensitive)
      K  = keyword coverage %  (job-skill names in resume text)
      D  = avg demand% of missing skills             (penalises market-critical gaps)

    The semantic sub-matrix is computed in one vectorised call (fast).
    O, K, D are computed in a nested loop because they require set operations
    per pair; for the typical evaluation sizes (≤20 × ≤200 = 4000 pairs)
    this runs in < 1 s.
    """
    # ── Semantic matrix (vectorised) ─────────────────────────────────────────
    dim = next((len(v) for v in emb_cache.values()), 1)
    zero = [0.0] * dim
    r_embs = np.array([emb_cache.get(r.raw_text, zero) for r in resumes])
    j_embs = np.array([emb_cache.get(j.description, zero) for j in jobs])

    norms_r = np.linalg.norm(r_embs, axis=1, keepdims=True)
    norms_j = np.linalg.norm(j_embs, axis=1, keepdims=True)
    if np.any(norms_r == 0) or np.any(norms_j == 0):
        sem_mat = np.zeros((len(resumes), len(jobs)))
    else:
        sem_mat = _cosine(r_embs, j_embs)

    # ── Per-pair O, K, D ─────────────────────────────────────────────────────
    scores = np.zeros((len(resumes), len(jobs)))

    for i, resume in enumerate(resumes):
        r_set = {s.strip().lower() for s in resume.skill_names}
        r_text = (resume.raw_text or "").lower()

        for j, job in enumerate(jobs):
            j_set = {s.strip().lower() for s in job.skill_names}
            n_j = len(j_set)

            S = float(sem_mat[i, j]) * 100.0

            if n_j > 0:
                matched = r_set & j_set
                missing = j_set - r_set
                O = len(matched) / n_j * 100.0
                K = sum(1 for s in j_set if s in r_text) / n_j * 100.0
                demand_vals = [demand_data.get(s, 0.0) for s in missing]
                D = float(np.mean(demand_vals)) if demand_vals else 0.0
            else:
                O, K, D = 100.0, 100.0, 0.0

            raw = (
                WEIGHT_SEMANTIC * S
                + WEIGHT_SKILL_OVERLAP * O
                + WEIGHT_KEYWORD * K
                - WEIGHT_DEMAND_PENALTY * D
            )
            scores[i, j] = max(0.0, min(100.0, raw))

    return scores


# ============================================================================
# Retrieval metrics
# ============================================================================

def precision_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    """Fraction of top-k retrieved items that are relevant."""
    if k <= 0:
        return 0.0
    return sum(1 for idx in ranked[:k] if idx in relevant) / k


def recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    """Fraction of all relevant items found in top-k results."""
    if not relevant:
        return 1.0
    return sum(1 for idx in ranked[:k] if idx in relevant) / len(relevant)


def mrr_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    """Reciprocal rank of the first relevant item in top-k (0 if none found)."""
    for rank, idx in enumerate(ranked[:k], start=1):
        if idx in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    """
    NDCG@k with binary relevance and log2 position discount.

    DCG  = Σ_{i=1}^{k}  rel_i / log2(i + 1)
    IDCG = Σ_{i=1}^{min(|R|,k)}  1 / log2(i + 1)   (ideal ranking)
    NDCG = DCG / IDCG
    """
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, idx in enumerate(ranked[:k], start=1)
        if idx in relevant
    )
    ideal = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1))
    return dcg / idcg if idcg > 0.0 else 0.0


# ============================================================================
# Evaluation loop
# ============================================================================

MetricsDict = dict[str, float]


def evaluate(
    score_matrix: np.ndarray,
    relevance: dict[tuple[int, int], bool],
    ks: list[int],
) -> tuple[MetricsDict, list[float]]:
    """
    Compute mean retrieval metrics across all resumes that have ≥1 relevant job.

    Returns:
        mean_metrics  — dict of metric_name → mean value across evaluated resumes
        ndcg5_per_resume — list of per-resume NDCG@5 values (for bootstrap CI)
    """
    n_resumes, n_jobs = score_matrix.shape
    accum: dict[str, list[float]] = {
        **{f"P@{k}": [] for k in ks},
        **{f"R@{k}": [] for k in ks},
        **{f"NDCG@{k}": [] for k in ks},
        "MRR": [],
    }
    ndcg5_per_resume: list[float] = []
    max_k = max(ks)

    for i in range(n_resumes):
        relevant = _relevant_jobs_for_resume(i, n_jobs, relevance)
        if not relevant:
            continue

        ranked: list[int] = np.argsort(-score_matrix[i]).tolist()

        for k in ks:
            accum[f"P@{k}"].append(precision_at_k(ranked, relevant, k))
            accum[f"R@{k}"].append(recall_at_k(ranked, relevant, k))
            accum[f"NDCG@{k}"].append(ndcg_at_k(ranked, relevant, k))

        accum["MRR"].append(mrr_at_k(ranked, relevant, max_k))

        # Collect NDCG@5 for bootstrap CI (use 5 if in ks, else max ks ≤ 5)
        ci_k = 5 if 5 in ks else min(ks, key=lambda x: abs(x - 5))
        ndcg5_per_resume.append(ndcg_at_k(ranked, relevant, ci_k))

    mean_metrics = {
        key: float(np.mean(vals)) if vals else 0.0
        for key, vals in accum.items()
    }
    return mean_metrics, ndcg5_per_resume


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = _RANDOM_SEED,
) -> tuple[float, float]:
    """
    Non-parametric bootstrap confidence interval for the mean.
    Returns (lower_bound, upper_bound) at the given confidence level.
    """
    if not values:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.array(values)
    boot_means = [
        float(np.mean(rng.choice(arr, size=len(arr), replace=True)))
        for _ in range(n_resamples)
    ]
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(boot_means, alpha))
    hi = float(np.quantile(boot_means, 1.0 - alpha))
    return lo, hi


# ============================================================================
# Output helpers
# ============================================================================

def _divider(width: int, char: str = "─") -> str:
    return char * width


def print_results_table(
    results: dict[str, MetricsDict],
    ci_data: dict[str, tuple[float, float]],
    ks: list[int],
) -> None:
    """
    Print the main comparison table:

      Model               Precision@5   Recall@5   NDCG@10     MRR
      ───────────────────────────────────────────────────────────────
      TF-IDF                  0.3200      0.1800    0.3541    0.4800
      Embedding-only          0.4000      0.2200    0.4210    0.5600
      Production Model        0.5400      0.3000    0.5810    0.7200   ★
    """
    # Determine which K values appear in the main display
    k_p = 5 if 5 in ks else ks[-2] if len(ks) >= 2 else ks[-1]
    k_r = k_p
    k_n = 10 if 10 in ks else ks[-1]

    display_metrics = [f"P@{k_p}", f"R@{k_r}", f"NDCG@{k_n}", "MRR"]
    header_labels = [f"Precision@{k_p}", f"Recall@{k_r}", f"NDCG@{k_n}", "MRR"]

    name_w, col_w = 22, 14
    total_w = name_w + col_w * len(header_labels)

    # Find best model per metric
    best: dict[str, str] = {}
    for m in display_metrics:
        best[m] = max(results.keys(), key=lambda n: results[n].get(m, 0.0))

    print()
    print("  " + "═" * total_w)
    print("  Resume–Job Matching Evaluation — Retrieval Metrics")
    print("  " + "═" * total_w)
    # Header row
    hdr = f"  {'Model':<{name_w}}" + "".join(f"{h:>{col_w}}" for h in header_labels)
    print(hdr)
    print("  " + _divider(total_w))

    model_order = ["TF-IDF", "Embedding-only", "Production Model"]
    for model in model_order:
        if model not in results:
            continue
        metrics = results[model]
        is_best = any(best.get(m) == model for m in display_metrics)
        marker = " ★" if is_best else "  "
        row = f"  {model:<{name_w}}"
        for m in display_metrics:
            val = metrics.get(m, 0.0)
            is_col_best = best.get(m) == model
            cell = f"{val:.4f}"
            if is_col_best:
                cell = f"[{cell}]"   # highlight best value
            row += f"{cell:>{col_w}}"
        print(row + marker)

    print("  " + _divider(total_w))

    # CI row for NDCG@{ci_k}
    ci_k = 5 if 5 in ks else ks[-1]
    print(f"\n  Bootstrap 95% CI for NDCG@{ci_k}  (1000 resamples):")
    for model in model_order:
        if model not in ci_data:
            continue
        lo, hi = ci_data[model]
        mu = results[model].get(f"NDCG@{ci_k}", 0.0)
        print(f"    {model:<22}  {mu:.4f}  [{lo:.4f}, {hi:.4f}]")
    print()


def print_improvement(
    results: dict[str, MetricsDict],
    ndcg_key: str,
) -> None:
    """Print relative and absolute improvement of Production Model vs baselines."""
    prod_val = results.get("Production Model", {}).get(ndcg_key, 0.0)

    print(f"  Improvement of Production Model ({ndcg_key}):")
    for baseline in ("TF-IDF", "Embedding-only"):
        base_val = results.get(baseline, {}).get(ndcg_key, 0.0)
        abs_diff = prod_val - base_val
        sign = "+" if abs_diff >= 0 else ""
        if base_val > 0:
            rel = abs_diff / base_val * 100.0
            print(
                f"    vs {baseline:<18}  {sign}{abs_diff:.4f} absolute  "
                f"({sign}{rel:.1f}% relative)  "
                f"[{prod_val:.4f} vs {base_val:.4f}]"
            )
        elif prod_val > 0:
            print(f"    vs {baseline:<18}  +∞ (baseline = 0.0000)")
        else:
            print(f"    vs {baseline:<18}  no improvement possible (both = 0.0000)")
    print()


def print_full_table(results: dict[str, MetricsDict], ks: list[int]) -> None:
    """Print every K value for every model."""
    all_metrics = (
        [f"P@{k}" for k in ks]
        + [f"R@{k}" for k in ks]
        + [f"NDCG@{k}" for k in ks]
        + ["MRR"]
    )
    col_w, m_w = 15, 12
    print("  Full metrics (all K):")
    header = f"  {'Metric':<{m_w}}" + "".join(f"{n:<{col_w}}" for n in results)
    print(header)
    print("  " + _divider(m_w + col_w * len(results)))
    for m in all_metrics:
        row = f"  {m:<{m_w}}" + "".join(
            f"{results[model].get(m, 0.0):<{col_w}.4f}"
            for model in results
        )
        print(row)
    print()


# ============================================================================
# CSV output
# ============================================================================

def save_summary_csv(
    results: dict[str, MetricsDict],
    ci_data: dict[str, tuple[float, float]],
    ks: list[int],
    path: str,
) -> None:
    """Save per-model mean metrics to CSV."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    all_metrics = (
        [f"P@{k}" for k in ks]
        + [f"R@{k}" for k in ks]
        + [f"NDCG@{k}" for k in ks]
        + ["MRR"]
    )
    ci_k = 5 if 5 in ks else ks[-1]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["model"] + all_metrics + [f"ndcg{ci_k}_ci_low", f"ndcg{ci_k}_ci_high"]
        )
        for model, metrics in results.items():
            lo, hi = ci_data.get(model, (0.0, 0.0))
            writer.writerow(
                [model]
                + [round(metrics.get(m, 0.0), 6) for m in all_metrics]
                + [round(lo, 6), round(hi, 6)]
            )
    print(f"  Summary CSV → {out}")


def save_per_resume_csv(
    score_matrices: dict[str, np.ndarray],
    relevance: dict[tuple[int, int], bool],
    resumes: list[ResumeRecord],
    ks: list[int],
    path: str,
) -> None:
    """Save per-resume NDCG@{max_k} for every model to a companion CSV."""
    out = Path(path).with_suffix("").parent / (Path(path).stem + "_per_resume.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    k = max(ks)
    n_jobs = next(iter(score_matrices.values())).shape[1]
    model_names = list(score_matrices.keys())

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["resume_id", "n_relevant"] + [f"NDCG@{k}_{m.replace(' ', '_')}" for m in model_names]
        )
        for i, resume in enumerate(resumes):
            rel = {j for j in range(n_jobs) if relevance.get((i, j), False)}
            if not rel:
                continue
            row: list = [resume.id, len(rel)]
            for name in model_names:
                ranked: list[int] = np.argsort(-score_matrices[name][i]).tolist()
                row.append(round(ndcg_at_k(ranked, rel, k), 6))
            writer.writerow(row)
    print(f"  Per-resume CSV  → {out}")


# ============================================================================
# Optional chart
# ============================================================================

def plot_comparison(
    results: dict[str, MetricsDict],
    ndcg_key: str,
    save_dir: str = "results",
) -> None:
    """
    Bar chart comparing all three models on NDCG@{k}.
    Saves to results/evaluation_chart.png and optionally displays it.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("  [plot] matplotlib not installed — skipping chart (pip install matplotlib)")
        return

    models = ["TF-IDF", "Embedding-only", "Production Model"]
    values = [results.get(m, {}).get(ndcg_key, 0.0) for m in models]
    colours = ["#6C8EBF", "#82B366", "#D6A54A"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(models, values, color=colours, edgecolor="white", linewidth=1.0)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.005,
            f"{val:.4f}",
            ha="center", va="bottom", fontsize=11, fontweight="bold",
        )

    # Improvement annotation
    prod_val = values[models.index("Production Model")]
    base_val = values[0]  # TF-IDF
    if base_val > 0:
        rel = (prod_val - base_val) / base_val * 100.0
        sign = "+" if rel >= 0 else ""
        ax.annotate(
            f"{sign}{rel:.1f}% vs TF-IDF",
            xy=(bars[2].get_x() + bars[2].get_width() / 2, prod_val),
            xytext=(bars[2].get_x() + bars[2].get_width() / 2, prod_val + 0.06),
            ha="center", fontsize=9, color="darkgreen",
            arrowprops=dict(arrowstyle="-", color="darkgreen", lw=0.5),
        )

    y_max = max(values) * 1.3 if values else 1.0
    ax.set_ylim(0, min(1.05, y_max))
    ax.set_ylabel(ndcg_key, fontsize=12)
    ax.set_title(
        f"Resume–Job Matching: {ndcg_key} Comparison\n"
        f"Score = 0.5·Semantic + 0.3·SkillOverlap + 0.2·Keyword − 0.2·DemandPenalty",
        fontsize=11,
    )
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    out = Path(save_dir) / "evaluation_chart.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Chart saved → {out}")
    plt.show()


# ============================================================================
# Main
# ============================================================================

async def main(args: argparse.Namespace) -> None:
    ks: list[int] = [1, 3, 5, 10]
    k_ndcg = 10 if 10 in ks else ks[-1]

    _banner("Resume–Job Matching — Evaluation Pipeline")
    t_total = time.perf_counter()

    # ── 1. Data ──────────────────────────────────────────────────────────────
    resumes, jobs, demand_data = await load_data(args.synthetic, args.limit)
    if not resumes or not jobs:
        _die("No data available. Use --synthetic to generate synthetic data.")

    # ── 2. Embeddings (one batched forward pass) ──────────────────────────────
    emb_cache = await build_embedding_cache(resumes, jobs)

    # ── 3. Ground truth ───────────────────────────────────────────────────────
    print("[truth]  Computing binary relevance (≥30% skill overlap) …", end="", flush=True)
    relevance = compute_relevance(resumes, jobs)
    n_pairs = len(resumes) * len(jobs)
    n_relevant = sum(1 for v in relevance.values() if v)
    n_eval_resumes = sum(
        1 for i in range(len(resumes))
        if any(relevance.get((i, j), False) for j in range(len(jobs)))
    )
    print(
        f" {n_relevant}/{n_pairs} relevant pairs "
        f"({n_relevant / n_pairs * 100:.1f}%)  |  "
        f"{n_eval_resumes}/{len(resumes)} resumes have ≥1 relevant job"
    )

    if n_eval_resumes == 0:
        _die(
            "No resumes have relevant jobs under the 30% overlap threshold.\n"
            "       Try --synthetic or check that skills are populated in the DB."
        )

    # ── 4. Score matrices ─────────────────────────────────────────────────────
    score_matrices: dict[str, np.ndarray] = {}

    _score_step("TF-IDF",          score_matrices,
                lambda: score_tfidf(resumes, jobs))
    _score_step("Embedding-only",  score_matrices,
                lambda: score_embedding_only(resumes, jobs, emb_cache))
    _score_step("Production Model", score_matrices,
                lambda: score_production_model(resumes, jobs, emb_cache, demand_data))

    # ── 5. Metrics + bootstrap CI ─────────────────────────────────────────────
    print("[metrics] Evaluating …")
    results: dict[str, MetricsDict] = {}
    ci_data: dict[str, tuple[float, float]] = {}

    for name, matrix in score_matrices.items():
        mean_metrics, ndcg5_vals = evaluate(matrix, relevance, ks)
        results[name] = mean_metrics
        ci_data[name] = bootstrap_ci(ndcg5_vals)

    elapsed = time.perf_counter() - t_total

    # ── 6. Output ─────────────────────────────────────────────────────────────
    print_results_table(results, ci_data, ks)
    print_improvement(results, ndcg_key=f"NDCG@{k_ndcg}")

    if args.verbose:
        print_full_table(results, ks)

    print(
        f"  Dataset : {len(resumes)} resumes × {len(jobs)} jobs  "
        f"(evaluated: {n_eval_resumes} resumes)\n"
        f"  Runtime : {elapsed:.2f}s total"
    )
    print()

    # ── 7. Optional outputs ───────────────────────────────────────────────────
    if args.output_csv:
        save_summary_csv(results, ci_data, ks, args.output_csv)
        save_per_resume_csv(score_matrices, relevance, resumes, ks, args.output_csv)

    if args.plot:
        plot_comparison(results, ndcg_key=f"NDCG@{k_ndcg}")


# ============================================================================
# Utility helpers
# ============================================================================

def _banner(text: str) -> None:
    width = max(len(text) + 4, 60)
    print()
    print("  " + "═" * width)
    print(f"  {'  ' + text:^{width}}")
    print("  " + "═" * width)
    print()


def _die(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)


def _score_step(
    name: str,
    matrices: dict[str, np.ndarray],
    fn: "callable",
) -> None:
    print(f"[score]  {name:<22} …", end="", flush=True)
    t0 = time.perf_counter()
    matrices[name] = fn()
    print(f" {time.perf_counter() - t0:.3f}s")


# ============================================================================
# CLI
# ============================================================================

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evaluate_advanced",
        description="Evaluate resume–job matching models (TF-IDF vs Embedding vs Production)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quickstart: synthetic data, no DB needed
  python3 -m scripts.evaluate_advanced --synthetic

  # Limit to 10 resumes
  python3 -m scripts.evaluate_advanced --synthetic --limit 10

  # Full run: save CSV and chart
  python3 -m scripts.evaluate_advanced --synthetic \\
      --output-csv results/eval_adv.csv --plot --verbose

  # Use real DB data
  python3 -m scripts.evaluate_advanced
""",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use deterministic synthetic data (20 resumes × 50 jobs). No DB required.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max number of resumes (default: all from DB, or 20 synthetic)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        metavar="PATH",
        help="Save summary + per-resume CSVs (e.g. results/eval_adv.csv)",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Save and display a bar chart of NDCG@10 (requires matplotlib)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full metrics for all K values",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(_parse_args()))
