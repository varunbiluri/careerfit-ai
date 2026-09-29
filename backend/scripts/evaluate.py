"""
Research-grade evaluation pipeline for CareerFit AI.

Usage (from backend/):
    python -m scripts.evaluate                        # use real DB data
    python -m scripts.evaluate --synthetic            # force 20 resumes × 50 jobs
    python -m scripts.evaluate --synthetic --k 5 10  # custom K values

What this produces
------------------
1. Formatted results table printed to stdout.
2. CSV saved to  results/evaluation_results.csv

Models evaluated
----------------
  TF-IDF           sklearn TF-IDF (1-2 gram, sublinear TF) cosine similarity
  BM25             BM25Okapi (rank_bm25)
  SkillOverlap     Pure skill-set Jaccard/recall: |R∩J|/|J|
  Embedding-A      Production weights  (ws=0.5, wo=0.3, wk=0.2)
  Embedding-B      Semantic-heavy      (ws=0.6, wo=0.2, wk=0.2)
  Embedding-C      Overlap-heavy       (ws=0.4, wo=0.4, wk=0.2)

Ground-truth (hybrid proxy)
----------------------------
  relevance_score = 0.5 * skill_overlap + 0.5 * semantic_similarity
  Both components are in [0, 1]; relevance_score ∈ [0, 1].
  A pair is "relevant" iff relevance_score > RELEVANCE_THRESHOLD (default 0.6).

  This is stronger than the naive ≥30% skill overlap used in the prototype:
  it penalises skill matches between semantically unrelated roles.

  Limitation: this is still an automated proxy, not human annotation.
  For publication, augment with recruiter-labelled pairs.

Metrics
-------
  Precision@K, Recall@K, MRR@K, NDCG@K  for K ∈ {1, 3, 5, 10}
  Bootstrap 95% CI on NDCG@5 (1 000 resamples, fixed seed).

Reproducibility
---------------
  All random operations use numpy.random.default_rng(RANDOM_SEED).
  Synthetic dataset is deterministic given n_resumes, n_jobs, RANDOM_SEED.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── make backend/app importable ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sk_cosine

# ── constants ─────────────────────────────────────────────────────────────────
RANDOM_SEED: int = 42
RELEVANCE_THRESHOLD: float = 0.60   # hybrid score above which a pair is "relevant"
N_BOOTSTRAP: int = 1_000            # bootstrap resamples for CI

# Weight configurations for grid search
WEIGHT_CONFIGS: list[dict[str, Any]] = [
    {"label": "Embedding-A (0.5·S+0.3·O+0.2·K)", "ws": 0.50, "wo": 0.30, "wk": 0.20},
    {"label": "Embedding-B (0.6·S+0.2·O+0.2·K)", "ws": 0.60, "wo": 0.20, "wk": 0.20},
    {"label": "Embedding-C (0.4·S+0.4·O+0.2·K)", "ws": 0.40, "wo": 0.40, "wk": 0.20},
]

# ── synthetic data ─────────────────────────────────────────────────────────────
_SKILL_POOL: list[str] = [
    "Python", "SQL", "TensorFlow", "PyTorch", "Docker", "Kubernetes",
    "AWS", "GCP", "Azure", "Spark", "Airflow", "dbt", "Pandas", "scikit-learn",
    "Git", "Linux", "MLOps", "NLP", "BERT", "Transformers", "XGBoost",
    "LightGBM", "Keras", "OpenCV", "FastAPI", "PostgreSQL", "Redis",
    "Kafka", "Snowflake", "Tableau", "Power BI", "CI/CD", "Terraform",
    "Java", "Scala", "MATLAB", "Statistics", "A/B testing",
    "Feature Engineering", "Model Deployment", "REST API", "GraphQL",
    "React", "TypeScript", "Node.js", "Elasticsearch", "MongoDB",
    "Hugging Face", "ONNX", "MLflow", "Weights & Biases", "Prometheus",
]

_ROLE_TEMPLATES: list[str] = [
    "Software engineer with {n} years of experience specializing in {skills1}. "
    "Built production systems using {skills2}. Passionate about {skills3}.",
    "Data scientist focused on {skills1} and {skills2}. "
    "Delivered ML models in {skills3} environment.",
    "ML engineer with deep expertise in {skills1}. "
    "Deployed {skills2} pipelines at scale. Familiar with {skills3}.",
    "Backend engineer skilled in {skills1}. "
    "Designed data systems using {skills2}. Experience with {skills3}.",
]

_JOB_TEMPLATES: list[str] = [
    "We seek a candidate proficient in {skills1}. "
    "Required: {skills2}. Nice to have: {skills3}.",
    "Join our team to build {skills1}-based systems. "
    "Must have: {skills2}. Bonus: {skills3}.",
    "Looking for engineer with {skills1} background. "
    "Day-to-day tools include {skills2}. Familiarity with {skills3} a plus.",
]


def _make_synthetic_dataset(
    n_resumes: int = 20,
    n_jobs: int = 50,
    seed: int = RANDOM_SEED,
) -> tuple[list[dict], list[dict]]:
    """Deterministic synthetic corpus. Each item has 'id', 'text', 'skills'."""
    rng = np.random.default_rng(seed)
    skills = _SKILL_POOL

    def _pick(n: int) -> list[str]:
        return [str(s) for s in rng.choice(skills, size=min(n, len(skills)), replace=False).tolist()]

    def _fmt_skills(lst: list[str]) -> str:
        return ", ".join(lst) if lst else "various technologies"

    resumes: list[dict] = []
    for i in range(n_resumes):
        n_skills = int(rng.integers(6, 20))
        skill_set = _pick(n_skills)
        tmpl = _ROLE_TEMPLATES[i % len(_ROLE_TEMPLATES)]
        n_exp = int(rng.integers(1, 8))
        text = tmpl.format(
            n=n_exp,
            skills1=_fmt_skills(skill_set[:5]),
            skills2=_fmt_skills(skill_set[5:10]),
            skills3=_fmt_skills(skill_set[10:]),
        )
        resumes.append({"id": i, "text": text, "skills": skill_set})

    jobs: list[dict] = []
    for j in range(n_jobs):
        n_skills = int(rng.integers(4, 14))
        skill_set = _pick(n_skills)
        tmpl = _JOB_TEMPLATES[j % len(_JOB_TEMPLATES)]
        text = tmpl.format(
            skills1=_fmt_skills(skill_set[:4]),
            skills2=_fmt_skills(skill_set[4:9]),
            skills3=_fmt_skills(skill_set[9:]),
        )
        jobs.append({"id": j, "text": text, "skills": skill_set})

    return resumes, jobs


# ── ground-truth ──────────────────────────────────────────────────────────────

def _skill_overlap_score(resume_skills: list[str], job_skills: list[str]) -> float:
    """Fraction of job skills present in resume (recall-oriented). Range [0, 1]."""
    if not job_skills:
        return 0.0
    rs = {s.lower() for s in resume_skills}
    return sum(1 for s in job_skills if s.lower() in rs) / len(job_skills)


def build_relevance_matrix(
    resumes: list[dict],
    jobs: list[dict],
    sem_sim_matrix: np.ndarray,   # (n_r, n_j) cosine similarities, in [0,1]
    threshold: float = RELEVANCE_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Hybrid relevance:  score = 0.5 * skill_overlap + 0.5 * semantic_similarity
    Both components are in [0, 1]; score ∈ [0, 1].

    Returns
    -------
    rel_scores  : float (n_r, n_j) — continuous relevance scores
    rel_binary  : int   (n_r, n_j) — 1 if rel_score > threshold else 0
    """
    n_r, n_j = len(resumes), len(jobs)
    rel_scores = np.zeros((n_r, n_j), dtype=float)

    for i, r in enumerate(resumes):
        for j, job in enumerate(jobs):
            so = _skill_overlap_score(r["skills"], job["skills"])
            ss = float(np.clip(sem_sim_matrix[i, j], 0.0, 1.0))
            rel_scores[i, j] = 0.5 * so + 0.5 * ss

    rel_binary = (rel_scores > threshold).astype(int)
    return rel_scores, rel_binary


# ── metric functions ──────────────────────────────────────────────────────────

def precision_at_k(ranked_labels: list[int], k: int) -> float:
    """P@k = |relevant ∩ top-k| / k"""
    if k <= 0:
        return 0.0
    return sum(ranked_labels[:k]) / k


def recall_at_k(ranked_labels: list[int], k: int, n_relevant: int) -> float:
    """R@k = |relevant ∩ top-k| / |relevant|"""
    if n_relevant == 0:
        return 0.0
    return sum(ranked_labels[:k]) / n_relevant


def mrr_at_k(ranked_labels: list[int], k: int) -> float:
    """MRR@k = 1 / rank_of_first_relevant  (0 if none in top-k)"""
    for rank, label in enumerate(ranked_labels[:k], start=1):
        if label == 1:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_labels: list[int], k: int, n_relevant: int) -> float:
    """
    NDCG@k with binary relevance.
      DCG@k  = Σ rel_i / log2(i+1)  for i=1..k
      IDCG@k = Σ 1 / log2(i+1)     for i=1..min(n_relevant, k)
      NDCG@k = DCG@k / IDCG@k
    """
    if n_relevant == 0 or k <= 0:
        return 0.0
    dcg = sum(
        label / np.log2(rank + 2)          # rank is 0-indexed; formula uses 1-indexed
        for rank, label in enumerate(ranked_labels[:k])
    )
    n_ideal = min(n_relevant, k)
    idcg = sum(1.0 / np.log2(rank + 2) for rank in range(n_ideal))
    return float(dcg / idcg) if idcg > 0 else 0.0


def bootstrap_ci(
    values: list[float],
    n_bootstrap: int = N_BOOTSTRAP,
    ci: float = 0.95,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """
    Bootstrap 95% CI for the mean of `values`.
    Statistically valid: samples from the empirical distribution.
    Returns (lower, upper).
    """
    if not values:
        return 0.0, 0.0
    _rng = rng if rng is not None else np.random.default_rng(RANDOM_SEED)
    arr = np.array(values)
    boot_means = np.array([
        np.mean(_rng.choice(arr, size=len(arr), replace=True))
        for _ in range(n_bootstrap)
    ])
    alpha = (1.0 - ci) / 2.0
    return float(np.quantile(boot_means, alpha)), float(np.quantile(boot_means, 1.0 - alpha))


# ── model scorers ─────────────────────────────────────────────────────────────

def _tfidf_scores(resume_texts: list[str], job_texts: list[str]) -> np.ndarray:
    """TF-IDF cosine similarity matrix (n_r, n_j). In [0, 1]."""
    vect = TfidfVectorizer(
        ngram_range=(1, 2),
        stop_words="english",
        min_df=1,
        sublinear_tf=True,
        norm="l2",
    )
    vect.fit(resume_texts + job_texts)
    r_vecs = vect.transform(resume_texts)
    j_vecs = vect.transform(job_texts)
    return sk_cosine(r_vecs, j_vecs)              # already in [0, 1] for l2-normed vecs


def _bm25_scores(resume_texts: list[str], job_texts: list[str]) -> np.ndarray:
    """
    BM25Okapi score matrix (n_r, n_j).
    Jobs are the corpus; resumes are the queries.
    Raw BM25 scores can exceed 1 — we min-max normalise per query row to [0, 1]
    so they are comparable to TF-IDF cosine.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        raise ImportError(
            "rank_bm25 not installed. Run:  uv add rank-bm25  or  pip install rank-bm25"
        )

    tokenised_corpus = [t.lower().split() for t in job_texts]
    bm25 = BM25Okapi(tokenised_corpus)

    n_r, n_j = len(resume_texts), len(job_texts)
    raw = np.zeros((n_r, n_j), dtype=float)
    for i, rt in enumerate(resume_texts):
        raw[i] = bm25.get_scores(rt.lower().split())

    # per-row min-max normalisation
    row_min = raw.min(axis=1, keepdims=True)
    row_max = raw.max(axis=1, keepdims=True)
    denom = np.where(row_max - row_min > 0, row_max - row_min, 1.0)
    return (raw - row_min) / denom


def _skill_overlap_scores(
    resume_skills: list[list[str]],
    job_skills: list[list[str]],
) -> np.ndarray:
    """Pure skill-overlap score matrix (n_r, n_j). In [0, 1]."""
    n_r, n_j = len(resume_skills), len(job_skills)
    mat = np.zeros((n_r, n_j), dtype=float)
    for i, rs in enumerate(resume_skills):
        rs_lower = {s.lower() for s in rs}
        for j, js in enumerate(job_skills):
            if js:
                mat[i, j] = sum(1 for s in js if s.lower() in rs_lower) / len(js)
    return mat


def _embedding_scores(
    sem_sim: np.ndarray,
    overlap_mat: np.ndarray,
    keyword_mat: np.ndarray,
    ws: float,
    wo: float,
    wk: float,
) -> np.ndarray:
    """Weighted embedding score matrix (n_r, n_j). Clipped to [0, 1]."""
    raw = ws * sem_sim + wo * overlap_mat + wk * keyword_mat
    return np.clip(raw, 0.0, 1.0)


def _keyword_coverage_matrix(
    resume_texts: list[str],
    job_skills: list[list[str]],
) -> np.ndarray:
    """
    Keyword@(i,j) = fraction of job j's skills whose name appears verbatim
    in resume text i. In [0, 1].
    """
    n_r, n_j = len(resume_texts), len(job_skills)
    mat = np.zeros((n_r, n_j), dtype=float)
    for i, rt in enumerate(resume_texts):
        rt_lower = rt.lower()
        for j, js in enumerate(job_skills):
            if js:
                mat[i, j] = sum(1 for s in js if s.lower() in rt_lower) / len(js)
    return mat


# ── per-model evaluation ──────────────────────────────────────────────────────

def _evaluate_model(
    score_matrix: np.ndarray,     # (n_r, n_j) — higher = better match
    rel_binary: np.ndarray,       # (n_r, n_j) — 1 = relevant
    k_values: list[int],
    rng: np.random.Generator,
) -> dict[str, Any]:
    """
    Compute Precision@K, Recall@K, MRR@K, NDCG@K for all K values.
    Metrics are computed per-resume then averaged (macro average).
    Bootstrap 95% CI computed on NDCG@5 per-resume values.

    Returns a flat dict:  { "P@1": 0.xx, "R@5": 0.xx, ... , "NDCG@5_ci": (lo, hi) }
    """
    n_r, n_j = score_matrix.shape
    max_k = max(k_values)

    # Accumulators: metric name → list of per-resume values
    per_resume: dict[str, list[float]] = {
        f"{m}@{k}": []
        for m in ("P", "R", "MRR", "NDCG") for k in k_values
    }

    ndcg5_values: list[float] = []   # for bootstrap CI

    for i in range(n_r):
        n_rel = int(rel_binary[i].sum())
        if n_rel == 0:
            continue   # skip resumes with zero relevant jobs in corpus

        ranked_idx = np.argsort(-score_matrix[i])
        ranked_labels = [int(rel_binary[i, idx]) for idx in ranked_idx]

        for k in k_values:
            per_resume[f"P@{k}"].append(precision_at_k(ranked_labels, k))
            per_resume[f"R@{k}"].append(recall_at_k(ranked_labels, k, n_rel))
            per_resume[f"MRR@{k}"].append(mrr_at_k(ranked_labels, k))
            ndcg_val = ndcg_at_k(ranked_labels, k, n_rel)
            per_resume[f"NDCG@{k}"].append(ndcg_val)
            if k == 5:
                ndcg5_values.append(ndcg_val)

    result: dict[str, Any] = {
        key: float(np.mean(vals)) if vals else 0.0
        for key, vals in per_resume.items()
    }
    result["n_queries"] = len(ndcg5_values)   # resumes with ≥1 relevant job
    ci_lo, ci_hi = bootstrap_ci(ndcg5_values, rng=rng)
    result["NDCG@5_ci_lo"] = ci_lo
    result["NDCG@5_ci_hi"] = ci_hi
    return result


# ── full experiment ───────────────────────────────────────────────────────────

def run_experiment(
    resumes: list[dict],
    jobs: list[dict],
    k_values: list[int] | None = None,
    relevance_threshold: float = RELEVANCE_THRESHOLD,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """
    Run the full evaluation pipeline.

    Returns a list of result dicts, one per model / weight config.
    Each dict has: model, ws, wo, wk, n_queries, P@k, R@k, MRR@k, NDCG@k, CI fields.
    """
    if k_values is None:
        k_values = [1, 3, 5, 10]

    rng = np.random.default_rng(RANDOM_SEED)
    resume_texts = [r["text"] for r in resumes]
    job_texts = [j["text"] for j in jobs]
    resume_skills = [r["skills"] for r in resumes]
    job_skills = [j["skills"] for j in jobs]

    # ── 1. Encode all texts once ────────────────────────────────────────────
    if verbose:
        print("  Loading embedding model and encoding all texts (one-time cost)...")
    t0 = time.perf_counter()
    from app.services.embedding_service import get_embeddings
    all_texts = resume_texts + job_texts
    all_embs = np.array(get_embeddings(all_texts))
    r_embs = all_embs[: len(resume_texts)]
    j_embs = all_embs[len(resume_texts):]
    sem_sim = sk_cosine(r_embs, j_embs)             # in [0, 1] (BGE embs are L2-normalised)
    t_emb = time.perf_counter() - t0
    if verbose:
        print(f"  Embedding done in {t_emb:.1f}s  "
              f"({len(all_texts)} texts → {all_embs.shape[1]}-dim)")

    # ── 2. Pre-compute shared component matrices ─────────────────────────────
    overlap_mat = _skill_overlap_scores(resume_skills, job_skills)
    keyword_mat = _keyword_coverage_matrix(resume_texts, job_skills)

    # ── 3. Build ground-truth ─────────────────────────────────────────────────
    rel_scores, rel_binary = build_relevance_matrix(
        resumes, jobs, sem_sim, threshold=relevance_threshold
    )
    n_relevant_pairs = int(rel_binary.sum())
    if verbose:
        avg_rel = rel_binary.sum(axis=1).mean()
        print(f"  Ground-truth built: {n_relevant_pairs} relevant pairs  "
              f"(avg {avg_rel:.1f} relevant jobs per resume,  threshold={relevance_threshold})")

    if n_relevant_pairs == 0:
        print("  WARNING: no relevant pairs found — lower RELEVANCE_THRESHOLD or add more data.")

    # ── 4. Score each model ───────────────────────────────────────────────────
    all_results: list[dict[str, Any]] = []

    def _add(label: str, matrix: np.ndarray, ws: float = 0, wo: float = 0, wk: float = 0) -> None:
        if verbose:
            print(f"  Evaluating {label}...")
        metrics = _evaluate_model(matrix, rel_binary, k_values, rng)
        all_results.append({"model": label, "ws": ws, "wo": wo, "wk": wk, **metrics})

    # Baselines
    if verbose:
        print("  Scoring TF-IDF...")
    _add("TF-IDF", _tfidf_scores(resume_texts, job_texts))

    try:
        if verbose:
            print("  Scoring BM25...")
        _add("BM25", _bm25_scores(resume_texts, job_texts))
    except ImportError as exc:
        print(f"  Skipping BM25 ({exc})")

    _add("SkillOverlap", overlap_mat)

    # Embedding variants (weight grid search)
    for cfg in WEIGHT_CONFIGS:
        mat = _embedding_scores(sem_sim, overlap_mat, keyword_mat, cfg["ws"], cfg["wo"], cfg["wk"])
        _add(cfg["label"], mat, ws=cfg["ws"], wo=cfg["wo"], wk=cfg["wk"])

    return all_results


# ── output helpers ─────────────────────────────────────────────────────────────

_COL_W = 28   # model column width

def _col(v: float, width: int = 7) -> str:
    return f"{v:.4f}".rjust(width)


def print_results_table(results: list[dict[str, Any]], k_values: list[int]) -> None:
    """Print a clean ASCII results table to stdout."""
    k_display = [k for k in k_values if k in (1, 3, 5, 10)]

    # Header
    cols = (
        [f"{'Model':<{_COL_W}}"]
        + [f"P@{k}".rjust(7) for k in k_display]
        + [f"R@{k}".rjust(7) for k in k_display]
        + ["MRR@5".rjust(9), "NDCG@5".rjust(9), "95% CI".rjust(16)]
    )
    header = "  ".join(cols)
    sep = "─" * len(header)

    print("\n" + sep)
    print(header)
    print(sep)

    for r in results:
        ci = f"[{r['NDCG@5_ci_lo']:.3f}, {r['NDCG@5_ci_hi']:.3f}]"
        row = (
            [f"{r['model']:<{_COL_W}}"]
            + [_col(r.get(f"P@{k}", 0.0)) for k in k_display]
            + [_col(r.get(f"R@{k}", 0.0)) for k in k_display]
            + [_col(r.get("MRR@5", 0.0), 9), _col(r.get("NDCG@5", 0.0), 9), f"{ci:>16}"]
        )
        print("  ".join(row))

    print(sep)
    print(f"\n  Queries with ≥1 relevant job: {results[0].get('n_queries', '?')} / {len(results[0].get('model', ''))} resumes")
    print(f"  Ground truth: hybrid relevance > {RELEVANCE_THRESHOLD}  "
          "(0.5·skill_overlap + 0.5·semantic_sim)")
    print("  Bootstrap CI: 95%, 1 000 resamples, fixed seed 42")
    print("  NOTE: proxy ground truth — not human-annotated. Replace for publication.\n")


def save_results_csv(
    results: list[dict[str, Any]],
    k_values: list[int],
    path: str | Path = "results/evaluation_results.csv",
) -> Path:
    """Save full metric table to CSV. Returns the path written."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    metric_cols = (
        [f"P@{k}" for k in k_values]
        + [f"R@{k}" for k in k_values]
        + [f"MRR@{k}" for k in k_values]
        + [f"NDCG@{k}" for k in k_values]
        + ["NDCG@5_ci_lo", "NDCG@5_ci_hi", "n_queries"]
    )
    fieldnames = ["model", "ws", "wo", "wk"] + metric_cols

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    return out_path


# ── DB loader ─────────────────────────────────────────────────────────────────

async def load_from_db(min_resumes: int = 5, min_jobs: int = 10) -> tuple[list[dict], list[dict]] | None:
    """Load resumes and jobs from production DB. Returns None if too few rows."""
    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from app.core.config import get_settings
        from app.models import Job, JobSkill, Resume, ResumeSkill, Skill

        settings = get_settings()
        engine = create_async_engine(settings.database_url, echo=False)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with sm() as session:
            resume_rows = (await session.execute(select(Resume).limit(200))).scalars().all()
            job_rows = (await session.execute(select(Job).limit(500))).scalars().all()

            if len(resume_rows) < min_resumes or len(job_rows) < min_jobs:
                return None

            resumes: list[dict] = []
            for r in resume_rows:
                stmt = (
                    select(Skill.name)
                    .join(ResumeSkill, ResumeSkill.skill_id == Skill.id)
                    .where(ResumeSkill.resume_id == r.id)
                )
                skills = list((await session.execute(stmt)).scalars().all())
                resumes.append({
                    "id": r.id,
                    "text": (r.raw_text or "") or " ".join(skills),
                    "skills": skills,
                })

            jobs: list[dict] = []
            for j in job_rows:
                stmt = (
                    select(Skill.name)
                    .join(JobSkill, JobSkill.skill_id == Skill.id)
                    .where(JobSkill.job_id == j.id)
                )
                skills = list((await session.execute(stmt)).scalars().all())
                jobs.append({
                    "id": j.id,
                    "text": (j.description or "") or " ".join(skills),
                    "skills": skills,
                })

        await engine.dispose()
        return resumes, jobs

    except Exception as exc:
        print(f"  DB load failed ({exc}); will fall back to synthetic data.")
        return None


# ── entry point ───────────────────────────────────────────────────────────────

async def main(
    use_synthetic: bool = False,
    k_values: list[int] | None = None,
    relevance_threshold: float = RELEVANCE_THRESHOLD,
    csv_path: str = "results/evaluation_results.csv",
) -> None:
    k_values = k_values or [1, 3, 5, 10]

    resumes: list[dict] | None = None
    jobs: list[dict] | None = None

    if not use_synthetic:
        print("Loading data from database...")
        data = await load_from_db()
        if data:
            resumes, jobs = data
            print(f"  Loaded {len(resumes)} resumes, {len(jobs)} jobs from DB.")
        else:
            print("  Insufficient DB data — switching to synthetic dataset.")

    if resumes is None:
        print("Generating synthetic dataset (20 resumes × 50 jobs, seed=42)...")
        resumes, jobs = _make_synthetic_dataset()
        print(f"  Generated {len(resumes)} resumes, {len(jobs)} jobs.")

    print(f"\nRunning evaluation   K={k_values}   threshold={relevance_threshold}")
    t0 = time.perf_counter()

    results = run_experiment(
        resumes, jobs,       # type: ignore[arg-type]
        k_values=k_values,
        relevance_threshold=relevance_threshold,
        verbose=True,
    )

    elapsed = time.perf_counter() - t0
    print(f"\nTotal evaluation time: {elapsed:.1f}s")

    print_results_table(results, k_values)

    out = save_results_csv(results, k_values, csv_path)
    print(f"Results saved to: {out.resolve()}\n")

    # ── interpretation ────────────────────────────────────────────────────────
    ndcg5_col = "NDCG@5"
    best = max(results, key=lambda r: r.get(ndcg5_col, 0.0))
    baselines = [r for r in results if r["model"] in ("TF-IDF", "BM25", "SkillOverlap")]
    best_baseline = max(baselines, key=lambda r: r.get(ndcg5_col, 0.0)) if baselines else None

    print("── Interpretation ─────────────────────────────────────────────────────────")
    print(f"  Best model by NDCG@5: {best['model']}  ({best.get(ndcg5_col, 0):.4f})")
    if best_baseline:
        delta = best.get(ndcg5_col, 0) - best_baseline.get(ndcg5_col, 0)
        print(f"  Best baseline:        {best_baseline['model']}  ({best_baseline.get(ndcg5_col, 0):.4f})")
        print(f"  ΔNDCG@5 over baseline: {delta:+.4f}")
    print()
    print("  Weight tuning summary (Embedding variants by NDCG@5):")
    emb_rows = [r for r in results if r["model"].startswith("Embedding")]
    emb_rows.sort(key=lambda r: -r.get(ndcg5_col, 0))
    for r in emb_rows:
        ci = f"[{r['NDCG@5_ci_lo']:.3f},{r['NDCG@5_ci_hi']:.3f}]"
        print(f"    {r['model']:<45}  NDCG@5={r.get(ndcg5_col,0):.4f}  95%CI={ci}")
    print("──────────────────────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Research-grade evaluation: TF-IDF vs BM25 vs Embedding (weight grid search)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Force synthetic dataset (20 resumes × 50 jobs)",
    )
    parser.add_argument(
        "--k", type=int, nargs="+", default=[1, 3, 5, 10],
        metavar="K", help="Rank cutoff values, e.g. --k 1 5 10",
    )
    parser.add_argument(
        "--threshold", type=float, default=RELEVANCE_THRESHOLD,
        help="Hybrid relevance threshold for binary label",
    )
    parser.add_argument(
        "--csv", type=str, default="results/evaluation_results.csv",
        help="Path to save CSV results",
    )
    args = parser.parse_args()

    asyncio.run(main(
        use_synthetic=args.synthetic,
        k_values=sorted(set(args.k)),
        relevance_threshold=args.threshold,
        csv_path=args.csv,
    ))
