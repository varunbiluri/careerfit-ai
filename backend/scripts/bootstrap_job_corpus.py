#!/usr/bin/env python3
"""
Generate backend/data/job_corpus.json with 250+ deduplicated job postings.

Run from repo root:
  cd backend && uv run python scripts/bootstrap_job_corpus.py

Skills are lowercase; titles and descriptions vary by template.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

RNG = random.Random(42)

ROLES = [
    ("Machine Learning Engineer", "ml"),
    ("Senior ML Engineer", "ml"),
    ("Data Scientist", "ds"),
    ("Applied Scientist", "ds"),
    ("Data Engineer", "de"),
    ("Senior Data Engineer", "de"),
    ("Backend Software Engineer", "be"),
    ("Full Stack Engineer", "fs"),
    ("DevOps Engineer", "ops"),
    ("Site Reliability Engineer", "ops"),
    ("Cloud Engineer", "cloud"),
    ("AI Engineer", "ml"),
    ("NLP Engineer", "nlp"),
    ("Computer Vision Engineer", "cv"),
    ("MLOps Engineer", "mlops"),
    ("Software Engineer", "se"),
    ("Senior Software Engineer", "se"),
    ("Platform Engineer", "be"),
    ("Security Engineer", "sec"),
    ("QA Automation Engineer", "qa"),
    ("Product Engineer", "se"),
    ("Analytics Engineer", "de"),
    ("Research Engineer", "ml"),
    ("Embedded Software Engineer", "emb"),
    ("Mobile Engineer", "mob"),
]

SKILL_SETS: dict[str, list[str]] = {
    "ml": [
        "python", "pytorch", "tensorflow", "scikit-learn", "numpy", "pandas",
        "machine learning", "deep learning", "experiment tracking", "mlflow",
        "kubernetes", "docker", "aws", "model deployment", "feature engineering",
    ],
    "ds": [
        "python", "sql", "statistics", "pandas", "numpy", "jupyter", "a/b testing",
        "visualization", "tableau", "snowflake", "spark", "machine learning",
        "communication", "experiment design",
    ],
    "de": [
        "python", "sql", "airflow", "spark", "kafka", "etl", "dbt", "snowflake",
        "aws", "gcp", "data warehousing", "postgresql", "kubernetes", "docker",
    ],
    "be": [
        "java", "python", "go", "rest api", "microservices", "postgresql", "redis",
        "kubernetes", "docker", "aws", "distributed systems", "grpc",
    ],
    "fs": [
        "typescript", "react", "node.js", "rest api", "postgresql", "css",
        "aws", "docker", "ci/cd", "testing",
    ],
    "ops": [
        "kubernetes", "docker", "terraform", "aws", "prometheus", "grafana",
        "linux", "python", "ci/cd", "helm",
    ],
    "cloud": [
        "aws", "azure", "gcp", "kubernetes", "terraform", "networking", "iam",
        "python", "linux", "monitoring",
    ],
    "nlp": [
        "python", "pytorch", "transformers", "nlp", "hugging face", "tokenization",
        "machine learning", "aws", "docker",
    ],
    "cv": [
        "python", "pytorch", "opencv", "computer vision", "deep learning",
        "tensorflow", "cuda", "docker",
    ],
    "mlops": [
        "kubernetes", "mlflow", "python", "docker", "aws", "ci/cd", "monitoring",
        "feature stores", "model serving",
    ],
    "se": [
        "python", "java", "algorithms", "testing", "git", "agile", "sql",
        "rest api", "linux",
    ],
    "sec": [
        "security", "python", "aws", "networking", "threat modeling", "owasp",
        "kubernetes", "compliance",
    ],
    "qa": [
        "python", "selenium", "testing", "ci/cd", "jenkins", "api testing",
        "automation", "docker",
    ],
    "emb": [
        "c", "c++", "embedded", "rtos", "linux", "microcontrollers", "debugging",
    ],
    "mob": [
        "swift", "kotlin", "mobile development", "ios", "android", "rest api",
    ],
}


def _pick_skills(track: str, k: int) -> list[str]:
    pool = SKILL_SETS.get(track, SKILL_SETS["se"])
    picks = list(pool)
    RNG.shuffle(picks)
    out: list[str] = []
    for s in picks:
        if s not in out:
            out.append(s)
        if len(out) >= k:
            break
    return out


def _description(title: str, skills: list[str]) -> str:
    lead = (
        f"We are hiring a {title}. You will work with modern stacks and cross-functional teams. "
        f"Key technologies include {', '.join(skills[:6])}. "
    )
    tail = (
        "Collaborate on design reviews, ship reliable software, and improve observability. "
        "Strong communication and ownership expected."
    )
    return (lead + tail)[:1200]


def build_jobs(n: int = 280) -> list[dict]:
    seen: set[str] = set()
    jobs: list[dict] = []
    i = 0
    while len(jobs) < n:
        title, track = ROLES[i % len(ROLES)]
        variant = i // len(ROLES)
        if variant:
            title = f"{title} (Team {variant})"
        k = 6 + (i % 7)
        skills = _pick_skills(track, k)
        desc = _description(title, skills)
        sig = hashlib.sha256(f"{title}|{desc}".encode()).hexdigest()[:16]
        if sig in seen:
            i += 1
            continue
        seen.add(sig)
        jobs.append({"title": title, "description": desc, "skills": skills})
        i += 1
    return jobs


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "job_corpus.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(280)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(jobs)} jobs to {out}")


if __name__ == "__main__":
    main()
