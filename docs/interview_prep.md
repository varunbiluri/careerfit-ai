# Interview Prep: CareerFit AI

## 2-Minute Verbal Explanation

> "I built an end-to-end resume-to-market matching system. A user uploads a PDF resume; the backend uses pdfplumber to extract text, then KeyBERT — backed by a BGE sentence embedding model — to extract technical skills. The system then scrapes live LinkedIn job postings for India, stores them in Postgres, and computes a multi-component match score between the resume and each job.
>
> The score formula is `0.5 × semantic similarity + 0.3 × skill overlap + 0.2 × keyword coverage − 0.2 × demand penalty`. Semantic similarity is a cosine distance between BGE-small embeddings of the job description and resume. The demand penalty down-weights the score when the candidate is missing skills that appear frequently across the market — it's a signal of market-level gap, not just local mismatch.
>
> I replaced a fake statistical CI (`SE = 3/sqrt(n)`) with an honest heuristic, added per-skill explainability (score drop and score-if-added for each missing skill), and wrote a research-grade evaluation script with NDCG@K, a hybrid ground truth proxy, BM25 and TF-IDF baselines, bootstrap confidence intervals, and a weight grid search. There's also an optional Ollama LLM integration for structured JSON advice — gracefully disabled when not configured.
>
> The frontend is React + TypeScript with Vite, the backend is FastAPI async with asyncpg, and all embedding inference is offloaded to a thread executor so the event loop never blocks."

---

## Architecture Summary

```
User (browser)
    │  HTTPS
    ▼
React SPA (Vite, :5173)
    │  /api proxy
    ▼
FastAPI (uvicorn, :8000)
    │
    ├── POST /resumes/upload
    │       └── ResumeService: pdfplumber → KeyBERT → resume_skills table
    │
    ├── POST /analysis/resume-gap
    │       └── GapAnalysisService:
    │               1. ensure_resume_skills (idempotent)
    │               2. scrape LinkedIn (7-day cache, 2s polite delay)
    │               3. MatchService.compute_resume_gap → fit % / gap %
    │               4. LLM gap advice (optional, Ollama)
    │               5. categorize_missing_skills + generate_learning_path
    │
    ├── GET  /analysis/match?job_id=&resume_id=
    │       └── MatchService.compute_match:
    │               semantic (BGE cosine) + skill_overlap + keyword − demand_penalty
    │               → top_positive_factors / top_negative_factors (explainability)
    │               → missing_skill_impacts (score-if-added per skill)
    │
    └── GET  /analysis/market-trends
            └── skill_trends: weekly growth, volatility (CoV), top emerging

Services:
  EmbeddingService  — singleton BGE-small-en-v1.5, SHA256 LRU cache (512 slots),
                      run_in_executor for non-blocking async inference
  SkillService      — KeyBERT extraction, skills_dictionary.json blocklist + plausibility
  ScraperService    — LinkedIn portal plugin, httpx async, external_id dedup
  LLMService        — Ollama /api/generate, retry + prompt truncation, structured JSON output
  GapAnalysisService — orchestrates full gap pipeline; router is a thin 7-line adapter

Database (Postgres + asyncpg):
  resumes → resume_skills ↘
                            skills
  jobs    → job_skills    ↗
  UniqueConstraints on junction tables; FK indexes; created_at indexed for trend queries
```

---

## Key Design Decisions

### 1. Why BGE embeddings over TF-IDF?

TF-IDF treats every word independently — `"Python"` and `"PyTorch"` share no vocabulary. BGE-small-en-v1.5 encodes contextual meaning in 384 dimensions, so semantically related job descriptions score higher even when exact keywords don't overlap.

**Trade-off acknowledged**: BGE requires 100 MB disk, ~20–80 ms per encode call (CPU), and blocks the thread. Mitigated with:
- Singleton lazy load (cold start only)
- SHA256 LRU cache (512 slots, ~800 KB) to avoid re-encoding identical texts
- `run_in_executor` so FastAPI's event loop never stalls

**Evaluation result**: BGE-based scorer (Embedding-A/C) achieved NDCG@5 = 1.000 vs TF-IDF's 0.677 on our synthetic benchmark with hybrid ground truth.

---

### 2. Why a demand penalty?

Skill overlap alone doesn't distinguish between missing a niche tool and missing AWS in a cloud-heavy role. The demand penalty (`−0.2 × avg_demand%_of_missing_skills`) down-weights scores proportionally to how market-critical the missing skills are.

**Example**: Missing `AWS` (appeared in 68% of scraped jobs) vs missing `LaTeX` (3%) — same overlap score, but the first should score lower.

**Trade-off**: The penalty was originally double-counted (applied twice via two separate code paths). Fixed: now computed once from the missing-skills list after deduplication.

---

### 3. Why remove the fake CI?

The original code reported `score_ci_95_lower = score − 3/sqrt(n)` styled as a 95% CI. This is invalid statistics — `n` here is the number of job skills, not a sample size. A CI requires a sampling distribution.

Replaced with an `uncertainty_score` (0–30, inversely proportional to sqrt of reference skill count): honest, non-misleading, still informative. A score computed from 2 job skills is less reliable than one computed from 20.

---

### 4. Why KeyBERT top_n=15 instead of 35?

Higher `top_n` extracts more candidate phrases but degrades precision — generic bigrams like `"developed various"` or `"team collaboration"` slip through. At top_n=15, KeyBERT's keyword quality is high enough that a secondary LLM verification pass is unnecessary, cutting resume upload time by 15–30 seconds per PDF.

---

### 5. Optional LLM layer

LLM advice (structured JSON with fit level, bullet improvements, rewritten bullets, metrics) is gated on `LLM_BASE_URL`. When the variable is empty, all LLM code paths short-circuit and return `None` — no external dependency required for a working demo.

Reliability improvements: 2-retry exponential backoff, prompt truncation (resume ≤ 800 words, job desc ≤ 1000 chars, skill lists ≤ 10–20 items), `"format": "json"` flag on structured prompts.

---

### 6. Async architecture correctness

FastAPI runs on a single-threaded async event loop. Three failure modes were fixed:

| Problem | Root cause | Fix |
|---|---|---|
| Event loop block on inference | `model.encode()` is CPU-bound | `run_in_executor` in `get_embeddings_async()` |
| Fake sync HTTP in async scraper | `httpx.get()` instead of `await client.get()` | Replaced with async `httpx.AsyncClient` |
| Raw `ALTER TABLE` in `init_db()` | DDL in app startup can corrupt migrations | Removed; schema changes now go through Alembic |

---

### 7. Evaluation methodology

**Why synthetic data?** No labeled resume-job relevance dataset is publicly available for Indian tech jobs. We generate deterministic synthetic data with `np.random.default_rng(42)` and use a hybrid proxy ground truth: `relevance = 0.5×skill_overlap + 0.5×semantic_similarity`, threshold 0.6.

**Why NDCG?** NDCG@K accounts for ranking position — a relevant job at rank 1 is worth more than one at rank 5. P@K is binary and ignores rank; MRR measures only the first relevant result.

**Bootstrap CI**: 1000 resamples from the per-resume NDCG@5 distribution. Valid because we resample empirical observations (each resume is an i.i.d. sample), not parametric assumptions.

---

## Structured Log Events (for observability dashboards)

| Event | Fields | Where |
|---|---|---|
| `embedding_latency_ms` | `n_texts`, `cache_hits` | `embedding_service.py` |
| `llm_latency_ms` | `model`, `prompt_chars` | `llm_service.py` |
| `request` | `method`, `path`, `status`, `duration_ms` | `main.py` middleware |

Grep for these structured keys in any log aggregator (Loki, Datadog, CloudWatch):
```
grep "embedding_latency_ms" app.log | awk -F= '{print $2}'
```
