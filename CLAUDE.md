# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack web application that analyzes resume–job skill gaps using transformer embeddings and demand-weighted scoring. Users upload a PDF resume; the app scrapes LinkedIn jobs, extracts skills, and computes a market fit score.

## Development Commands

### Database Setup
```bash
createdb ai_resume_analyzer            # One-time: create the PostgreSQL database
uv sync --extra migrate                # Install alembic
uv run alembic upgrade head            # Apply all DB migrations
```

### Backend (Python 3.11, managed with `uv`)
```bash
cd backend
uv venv && uv sync          # Create venv and install deps
cp .env.example .env        # Configure environment
uv run uvicorn app.main:app --reload  # Start API on :8000
uv run arq worker.WorkerSettings      # Start ARQ background worker (requires Redis)
```

API docs available at `http://127.0.0.1:8000/docs` (Swagger) and `/redoc`.

### Testing
```bash
uv sync --extra dev                              # Install pytest + pytest-asyncio
uv run pytest                                    # Run all tests
uv run pytest tests/test_foo.py::test_bar -v    # Run a single test
```
Tests go in `backend/tests/`.

### Frontend (Node.js)
```bash
cd frontend
npm install
npm run dev      # Dev server on :5173 (proxies /api → :8000)
npm run build    # Production build
npm run preview  # Preview production build locally
```

### Docker (backend only)
```bash
cd backend
docker build -t ai-job-market-api .
docker run -p 8000:8000 --env-file .env ai-job-market-api
```

## Architecture

### Backend (`backend/app/`)
FastAPI + SQLAlchemy (async) + PostgreSQL via asyncpg.

**Services layer** (`services/`) is the core business logic:
- `embedding_service.py` — Singleton SentenceTransformer (`BAAI/bge-small-en-v1.5`); lazy-loaded once, reused for all requests
- `skill_service.py` — Skill extraction (KeyBERT + `data/skills_dictionary.json`), blocklist filtering, demand % calculations
- `match_service.py` — Scoring: `Score = 0.5×Semantic + 0.3×SkillOverlap + 0.2×Keyword − 0.2×DemandPenalty` with 95% CI
- `scraper_service.py` — LinkedIn scraping (India, last 24h hardcoded); jobs cached 7 days by `external_id` hash
- `resume_service.py` — PDF text extraction via pdfplumber
- `llm_service.py` — Optional Ollama integration (disabled when `LLM_BASE_URL` is empty)
- `adzuna_service.py` — Alternative job board adapter

**Production infrastructure** (`cache/`, `worker/`, `core/`):
- `cache/redis_client.py` — Async Redis pool with graceful degradation; used as L2 embedding cache (TTL 24h, key `emb:{sha256}`)
- `worker/tasks.py` — ARQ task definitions: `gap_analysis_task`, `prescrape_jobs` (cron), `background_scrape_task`
- `worker/settings.py` — ARQ `WorkerSettings`; `worker.py` is the top-level entrypoint
- `core/security.py` — JWT (PyJWT) + bcrypt password hashing; `core/deps.py` provides `get_current_user` FastAPI dep
- `core/limiter.py` — Single `slowapi.Limiter` instance shared across all routers
- `prometheus-fastapi-instrumentator` — Metrics exposed at `/metrics`

**Routers** (`routers/`): `auth`, `resumes`, `jobs`, `analysis`, `scraper`, `admin`

**Job board plugin system** in `portals/`: `linkedin.py` + `registry.py`

**LLM prompts** stored in `data/prompts.json`.

### Frontend (`frontend/src/`)
React 18 + TypeScript + Vite + Tailwind CSS.

- `App.tsx` — Routes: `/` (Landing) and `/dashboard` (Dashboard)
- `pages/Dashboard.tsx` — Main UX: upload, gap analysis, job list, match modal
- `api/client.ts` — Axios HTTP client (base URL: `/api`)
- `contexts/` — Theme context (dark/light toggle)
- Key components: `CircularScore`, `SkillDemandChart`, `MatchScoreBreakdown`, `GapAdviceStructured`, `MatchAdviceStructured`

### Key Configuration (`backend/app/core/config.py`)
| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ai_resume_analyzer` | |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Downloaded on first use |
| `SIMILARITY_THRESHOLD` | `0.6` | Cosine similarity cutoff |
| `LLM_BASE_URL` | `http://localhost:11434` | Leave empty to disable Ollama |
| `LLM_MODEL` | `llama3.2` | Ollama model name |
| `SCRAPER_CACHE_DAYS` | `7` | Job deduplication window |
| `REDIS_URL` | `redis://localhost:6379/0` | Set empty to disable Redis/ARQ/caching |
| `JWT_SECRET_KEY` | *(placeholder)* | Must be strong random bytes in production |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) | JWT lifetime |
| `SKILL_SIMILARITY_THRESHOLD` | `0.72` | Embedding similarity for skill matching |
| `SEMANTIC_MATCH_THRESHOLD` | `0.80` | Threshold for semantic match hits |
| `SCRAPER_DELAY` | `2` | Seconds between scraper requests |
| `USE_EMBEDDING_SKILL_EXTRACTION` | `false` | Toggle embedding-based skill extraction |
| `USE_SEMANTIC_SKILL_MATCHING` | `false` | Toggle semantic skill matching |

## Key Data Flows

**Resume Upload** → pdfplumber extracts text → KeyBERT extracts skills → stored in `resumes` + `resume_skills` tables → optional LLM summary.

**Gap Analysis (background)** → `POST /analysis/resume-gap` enqueues ARQ task → returns `{"task_id": "...", "status": "queued"}` (HTTP 202) → worker runs GapAnalysisService → result stored in Redis → poll `GET /analysis/status/{task_id}`. Falls back to inline sync if Redis unavailable.

**Pre-scraping (cron)** → ARQ cron fires `prescrape_jobs` at 00:00, 06:00, 12:00, 18:00 → scrapes top-demand skills from market → DB stays warm → gap analysis requests skip live scraping.

**Auth** → `POST /auth/register` or `/auth/login` → JWT returned → include `Authorization: Bearer <token>` on upload/gap requests for user isolation.

**Job Match** → resume + job texts encoded by EmbeddingService → 4-component score with CI → optional LLM match advice.
