#!/usr/bin/env python3
"""
Export ranking-style metrics for research (Precision@K, MRR, NDCG).

Uses the same deterministic synthetic generator as scripts/evaluate.py when
the database is unavailable. For production evaluation, point at a frozen
export of job_corpus.json + resume fixtures.

Usage:
  cd backend && uv run python scripts/export_metrics.py
  cd backend && uv run python scripts/export_metrics.py --synthetic --k 5 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

# Allow running as script from backend/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _precision_recall_at_k(relevant: set[int], ranked: list[int], k: int) -> tuple[float, float]:
    top = ranked[:k]
    hit = sum(1 for i in top if i in relevant)
    p = hit / k if k else 0.0
    r = hit / len(relevant) if relevant else 0.0
    return p, r


def _mrr(relevant: set[int], ranked: list[int]) -> float:
    for i, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1.0 / i
    return 0.0


def _dcg_at_k(relevance: list[float], k: int) -> float:
    dcg = 0.0
    for i, rel in enumerate(relevance[:k]):
        dcg += (2**rel - 1) / math.log2(i + 2)
    return dcg


def _ndcg_at_k(relevance: list[float], k: int) -> float:
    dcg = _dcg_at_k(relevance, k)
    ideal = sorted(relevance, reverse=True)
    idcg = _dcg_at_k(ideal, k)
    return (dcg / idcg) if idcg > 0 else 0.0


def demo_synthetic_metrics(k_list: list[int]) -> dict:
    """Toy example: 1 query, binary relevance, fixed ranking."""
    relevant = {0, 2, 5}
    ranked = [2, 7, 0, 1, 5, 3, 4, 6]
    rel_vec = [1.0 if i in relevant else 0.0 for i in ranked]
    out: dict = {"mode": "synthetic_demo", "queries": 1}
    for k in k_list:
        p, r = _precision_recall_at_k(relevant, ranked, k)
        out[f"precision@{k}"] = round(p, 4)
        out[f"recall@{k}"] = round(r, 4)
        out[f"ndcg@{k}"] = round(_ndcg_at_k(rel_vec, k), 4)
    out["mrr"] = round(_mrr(relevant, ranked), 4)
    return out


async def main_async(args: argparse.Namespace) -> None:
    if args.synthetic or not args.from_db:
        metrics = demo_synthetic_metrics(args.k)
        print(json.dumps(metrics, indent=2))
        return
    # DB path: optional future hook — keep deterministic default for CI
    print(json.dumps({"error": "Use --synthetic or implement DB export in your study"}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Export Precision@K, MRR, NDCG")
    p.add_argument("--synthetic", action="store_true", help="Run deterministic toy example (no DB)")
    p.add_argument("--from-db", action="store_true", help="Future: load pairs from PostgreSQL")
    p.add_argument("--k", type=int, nargs="+", default=[5, 10], help="K values for P@K / NDCG")
    args = p.parse_args()
    if not args.from_db:
        args.synthetic = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
