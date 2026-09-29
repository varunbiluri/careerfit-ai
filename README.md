# CareerFit AI

**CareerFit AI** is an open-source career intelligence product that analyzes resume-job skill gaps with transformer embeddings, live market signals, and demand-weighted recommendations.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Open Source

CareerFit AI is released under the [MIT License](LICENSE). You can use, modify, self-host, and extend it for personal, academic, or commercial projects.

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), open an issue for bugs or feature ideas, and keep changes focused so they are easy to review.

**Stack:** **Backend** (FastAPI, SQLAlchemy async, PostgreSQL, BGE embeddings, LinkedIn scraping, optional local LLM) + **Frontend** (React, Vite, TypeScript, Tailwind, Recharts). Upload a resume, run **Analyze Skills Gap** to scrape LinkedIn (India, last 24h), then see fit %, gap %, matched/missing skills, and high-demand skills to learn. Resume–job match uses **Score = 0.5S + 0.3O + 0.2K − 0.2D** (semantic, overlap, keyword, demand-weight penalty) with a **95% confidence interval**. With a local LLM (e.g. Ollama), the app generates **AI resume summary** and **AI advice** for gap and match using the candidate’s resume text and LinkedIn job descriptions.

---

## Contents

| Section | Description |
|--------|-------------|
| [Architecture](#architecture) | High-level diagram, layers, main flows, external dependencies |
| [How the application behaves](#how-the-application-behaves) | User journey and what happens at each step |
| [1. Backend setup](#1-backend-uv-setup-commands) | uv, venv, database, run API |
| [2. pyproject.toml](#2-pyprojecttoml-backend) | Backend dependencies and build |
| [3. Backend folder structure](#3-backend-folder-structure) | Directory tree |
| [4. Frontend setup](#4-frontend-vite-setup-commands) | npm install, run dev |
| [5. Tailwind](#5-tailwind-setup) | Config and CSS |
| [6. API integration](#6-api-integration-example-axios) | Axios client and endpoints |
| [7. Pages & dashboard](#7-react-page-components--dashboard-structure) | Landing, Dashboard, components |
| [8. Run](#8-run-instructions) | Start backend and frontend |
| [Features](#features-checklist) | Checklist |
| [Docker](#docker-backend) | Backend container |
| [Environment](#environment) | Env vars and options |
| [Deploy](docs/DEPLOYMENT_CAPSTONE.md) | Render + Vercel deployment guide |
| [Improvements (AI + viz)](docs/IMPROVEMENTS.md) | AI, data science and visualization ideas |
| [Local LLM & prompts](docs/LOCAL_LLM_AND_PROMPTS.md) | Optional local model (Ollama) and prompt templates |

---

## Architecture

### High-level

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React + Vite)                         │
│  Landing  │  Dashboard: Upload resume → Select resume → Analyze Skills Gap  │
│           │  Gap result (fit %, gap %, skills) │ Available jobs │ Match %    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │ HTTP (REST)
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                              BACKEND (FastAPI)                               │
│  Routers: /resumes  /jobs  /analysis  /scraper                               │
│  Services: ResumeService, MatchService, ScraperService, EmbeddingService,   │
│            LLMService (optional: resume summary, gap/match advice)           │
│  Portals: LinkedInAdapter (build URL, parse job links)                        │
└───────────────┬─────────────────────────────────────┬───────────────────────┘
                │                                     │
                ▼                                     ▼
┌───────────────────────────────┐     ┌──────────────────────────────────────┐
│  PostgreSQL                   │     │  LinkedIn (public job search)         │
│  resumes, jobs, skills        │     │  Scrape search results + job pages   │
│  resume_skills, job_skills    │     │  Location: India, Time: last 24h     │
└───────────────────────────────┘     └──────────────────────────────────────┘
```

### Layers

| Layer | Responsibility |
|-------|----------------|
| **Frontend** | Upload PDF, list resumes/jobs, **Generate AI summary**, Analyze Skills Gap, gap result (fit %, skills, **AI advice**), high-demand chart, job list, resume–job **Match** (score breakdown + **AI advice**). |
| **Routers** | HTTP API: resume upload/list, **POST /resumes/{id}/generate-summary**, job list/detail, resume-gap, match, skill-demand, **market-trends**, scrape-search-page. |
| **Services** | **ResumeService**: PDF → text, extract skills (**dictionary + optional BGE embedding similarity**), store Resume + ResumeSkill; optional AI summary on upload. **ScraperService**: build LinkedIn URL (India, 24h), fetch and parse job pages, store Job + JobSkill. **MatchService**: resume gap (vs scraped jobs), resume–job match (BGE + skill + keyword). **EmbeddingService**: BGE, encode for similarity. **SkillService**: demand %, get_skills_for_scrape; **AI-based skill extraction** (embedding similarity over dictionary phrases) to detect unseen skills and variants. **LLMService** (optional): resume summary, gap advice, match advice using resume text + LinkedIn job descriptions. |
| **Portals** | **LinkedInAdapter**: build search URL from skill terms + location + time; parse job detail links from HTML. |
| **Data** | **PostgreSQL**: resumes (id, filename, raw_text, ai_summary), jobs (id, external_id, title, company, description, source), skills (id, name), resume_skills, job_skills. |

### Main flows

1. **Upload resume**  
   `POST /resumes/upload` → extract text (pdfplumber) → **extract skills** (dictionary + optional BGE embedding similarity for variants/unseen skills) → insert Resume + ResumeSkill.

2. **Analyze Skills Gap**  
   `POST /analysis/resume-gap` with `resume_id` → get resume skills + top market skills → **ScraperService.scrape_by_skills** (LinkedIn, India, last 24h) → store new jobs + JobSkill → **MatchService.compute_resume_gap** → return fit %, gap %, matched/missing, high-demand missing. If LLM enabled: **LLMService.gap_advice** with resume excerpt + sample LinkedIn job listings → `ai_advice` in response.

3. **Match resume to job**  
   `GET /analysis/match?job_id=&resume_id=` → BGE embeddings + skill overlap + keyword → match % and breakdown. If LLM enabled: **LLMService.match_advice** with resume excerpt + job description → `ai_advice` in response.

4. **Demand**  
   Demand % = (number of jobs mentioning the skill / total jobs) × 100; computed from DB (job_skills, jobs), no external API.

### External dependencies

- **LinkedIn**: public job search and job detail pages (HTTP + HTML parsing). Location and time (India, last 24h) are fixed in the backend.
- **Hugging Face**: BGE embedding model downloaded once, then runs locally.
- **Ollama** (optional): local LLM for AI summary and AI advice. Prompts use **resume text** and **LinkedIn job descriptions** for context-aware advice.

---

## How the application behaves

This section describes the **user journey** and what the app does at each step.

### 1. Landing page

- User opens the app (e.g. http://localhost:5173).
- Sees a **Landing** page: hero, short product explanation, **Upload Resume** button, feature highlights. Can toggle dark/light theme.
- Clicking **Upload Resume** (or nav) typically leads to the Dashboard.

### 2. Dashboard — Upload resume

- User **uploads a PDF resume** (Choose PDF / file input).
- **Backend:** PDF is read → text is extracted (pdfplumber) → skills are matched from a dictionary (`skills_dictionary.json`) → **Resume** and **ResumeSkill** rows are stored. If **LLM_BASE_URL** is set, the backend calls the local LLM to generate an **AI summary** (stored in `resumes.ai_summary`).
- **Frontend:** Shows success (e.g. “Resume uploaded, N skills extracted. AI summary generated.”) and the new resume appears in the list. User can also click **Generate AI summary** for the selected resume to create or refresh the summary.

### 3. Dashboard — Analyze Skills Gap

- User **selects a resume** from the dropdown and clicks **Analyze Skills Gap**.
- **Backend:**  
  - Loads that resume’s skills plus top “market” skills (from demand in the DB, or from the skills dictionary if there are no jobs yet).  
  - Builds a **LinkedIn job search URL** (India, last 24 hours).  
  - Fetches the LinkedIn search page, parses job listing links, then fetches each job page and extracts title, company, description.  
  - Stores **Job** and **JobSkill** rows (skills are extracted from job descriptions using the same dictionary).  
  - Compares the resume’s skills to **all skills** found across the stored jobs and computes **fit %** (how much of the market you match) and **gap %** (what you’re missing).  
  - Returns matched skills, missing skills, and **high-demand missing skills** (missing skills that appear in many jobs, so worth learning first).
- **Frontend:** Shows **Market fit %**, **Gap to close %**, your skills vs matched vs missing, **high-demand missing skills** (bar chart + cards), and, when LLM is enabled, **AI advice** (Prioritize / Highlight / Next step) based on the resume excerpt and sample LinkedIn job listings. Also “Jobs: X new, Y from cache.”

### 4. Dashboard — Available jobs

- The same Dashboard lists **Available jobs** (from the last scrape). Jobs that look like sign-in/login pages are filtered out from the list. Each job shows title, company, source, and a “View job” link to the original posting.

### 5. Match resume to job (optional)

- User selects a resume (same dropdown as gap) and clicks **Match** on a job in the Available jobs list.
- **Backend:** Job description and resume text → **BGE** embeddings; **Score = 0.5S + 0.3O + 0.2K − 0.2D** (semantic, overlap, keyword, demand penalty D = average demand % of missing skills); **95% CI** for the score. If LLM is enabled, **LLMService.match_advice** is called with the **resume excerpt** and **job description** (LinkedIn listing) to produce tailored **AI advice** (Fit / Highlight / Improve).
- **Frontend:** A modal shows the match score, breakdown chart (semantic, skill overlap, keyword), matched/missing skills, and **AI advice** when available.

### 6. Skill demand (optional)

- **Demand %** for each skill = (number of jobs that mention that skill / total jobs) × 100. It is computed from the database only (no external API). The Dashboard can show a skill demand chart (e.g. Recharts) for skills across all stored jobs.

### Summary

| User action | What the app does |
|-------------|-------------------|
| Upload PDF | Extract text → extract skills (dictionary) → save resume + skills; optional AI summary via LLM. |
| Generate AI summary | POST /resumes/{id}/generate-summary → LLM generates summary from resume text → stored in DB. |
| Analyze Skills Gap | Get resume + market skills → scrape LinkedIn (India, 24h) → save jobs + job skills → compute fit %, gap %, matched/missing, high-demand missing → optional AI advice (resume + LinkedIn job samples) → show result. |
| View jobs | List jobs from DB (scraped); hide sign-in-like entries. |
| Match resume to job | BGE + skill + keyword → match % and breakdown; optional AI advice (resume + job description). |
| Demand % | From DB: (jobs with skill / total jobs) × 100. |
| Market trend analytics | **GET /analysis/market-trends**: time-based skill trends (weekly growth %, volatility index, top emerging skills) over the last 8 weeks using `Job.created_at`. |

---

## Prerequisites

- **Python 3.11** (backend), **Node.js** (frontend), **PostgreSQL**, **[uv](https://docs.astral.sh/uv/)** for backend deps.

---

## 1. Backend uv setup commands

```bash
cd backend
uv venv
uv sync
cp .env.example .env
# Edit .env: DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/ai_resume_analyzer
```

Create DB (if needed):

```bash
createdb ai_resume_analyzer
```

Run API:

```bash
uv run uvicorn app.main:app --reload
```

- **API:** http://127.0.0.1:8000  
- **Docs:** http://127.0.0.1:8000/docs

---

## 2. pyproject.toml (backend)

Located at `backend/pyproject.toml`. Key content:

- **Python:** `>=3.11,<3.12`
- **Dependencies:** fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, sqlalchemy[asyncio], asyncpg, sentence-transformers, scikit-learn, torch, pdfplumber, httpx, beautifulsoup4, python-dotenv, python-multipart
- **Build:** hatchling, packages = ["app"]

---

## 3. Backend folder structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── logging.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── session.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── job.py
│   │   ├── skill.py
│   │   └── resume.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── job.py
│   │   ├── resume.py
│   │   └── match.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding_service.py
│   │   ├── skill_service.py
│   │   ├── resume_service.py
│   │   ├── match_service.py
│   │   ├── scraper_service.py
│   │   ├── llm_service.py
│   │   └── portals/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── registry.py
│   │       └── linkedin.py
│   └── routers/
│       ├── __init__.py
│       ├── jobs.py
│       ├── resume.py
│       ├── analysis.py
│       ├── scraper.py
│       └── admin.py
├── data/
│   ├── skills_dictionary.json
│   └── prompts.json
├── pyproject.toml
├── .env.example
├── .python-version
└── Dockerfile
```

---

## 4. Frontend Vite setup commands

```bash
cd frontend
npm install
npm run dev
```

To create a new Vite + React + TS project from scratch (reference only):

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
```

---

## 5. Tailwind setup

- **Config:** `frontend/tailwind.config.js` — `content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}']`, `darkMode: 'class'`
- **PostCSS:** `frontend/postcss.config.js` — `tailwindcss`, `autoprefixer`
- **CSS:** `frontend/src/index.css` — `@tailwind base; @tailwind components; @tailwind utilities;`
- **Dependencies:** `tailwindcss`, `autoprefixer`, `postcss` in `package.json` devDependencies

---

## 6. API integration example (Axios)

```typescript
// frontend/src/api/client.ts
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

export const resumesApi = {
  list: (params?: { skip?: number; limit?: number }) =>
    api.get<ResumeOut[]>('/resumes/', { params }),
  get: (id: number) => api.get(`/resumes/${id}`),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<ResumeOut>('/resumes/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  generateSummary: (id: number) =>
    api.post<{ id: number; ai_summary: string }>(`/resumes/${id}/generate-summary`, {}, { timeout: 90000 }),
}

export const analysisApi = {
  match: (jobId: number, resumeId: number) =>
    api.get<MatchResult>('/analysis/match', {
      params: { job_id: jobId, resume_id: resumeId },
    }),
  skillDemand: () => api.get<SkillDemandOut[]>('/analysis/skill-demand'),
  resumeGap: (resumeId: number) =>
    api.post<ResumeGapOut>('/analysis/resume-gap', { resume_id: resumeId }, { timeout: 120000 }),
}
```

Vite proxies `/api` to `http://127.0.0.1:8000` in dev (`vite.config.ts`).

---

## 7. React page components & dashboard structure

**Pages:**

- **Landing** (`src/pages/Landing.tsx`) — Hero, product explanation, “Upload Resume” CTA, feature highlights, dark/light toggle.
- **Dashboard** (`src/pages/Dashboard.tsx`) — Upload resume; **Analyze Skills Gap** (select resume → scrape LinkedIn → show gap); match resume to job; skill demand chart. Uses sidebar layout from `Layout`.

**Resume → gap flow:** User selects a resume. The app (1) **extracts** skills from the PDF (if needed), (2) **scrapes** LinkedIn job search (India, last 24 hours) using those skills plus top market-demand skills, (3) returns **fit %**, **gap %**, matched/missing skills, and high-demand missing skills to prioritize. **POST /analysis/resume-gap** with `{ "resume_id": id }` runs this; the Dashboard **Analyze Skills Gap** button calls it.

**Dashboard component structure:**

- **Layout** (`src/components/Layout.tsx`) — Left sidebar (nav: Dashboard; theme toggle), main content `<Outlet />`.
- **CircularScore** — Market fit % and match score circular progress.
- **SkillDemandChart** — Recharts bar chart for high-demand missing skills.
- **RecommendationCards** — High-demand missing skills as cards (name, demand %, job count).
- **MatchScoreBreakdown** — Bar chart for match formula (0.5S + 0.3O + 0.2K − 0.2D), demand penalty, and 95% CI.
- **LoadingSpinner** — Animated loading for upload, gap, match, and Generate AI summary.

**Routing:** `App.tsx` — `/` → Landing; `/app` → Layout with Dashboard.

---

## 8. Run instructions

**Quick start (backend + frontend):**

```bash
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```

Then open **http://localhost:5173** (app) and **http://127.0.0.1:8000/docs** (API docs).  

---

## Features checklist

| Feature | Status |
|--------|--------|
| Landing: hero, product explanation, Upload Resume CTA, feature highlights, SaaS UI | ✅ |
| Dashboard: upload, circular score, semantic match %, matched/missing/high-demand skills, skill demand graph | ✅ |
| Dashboard: left sidebar, main panel, recommendation cards | ✅ |
| Resume gap: extract skills → scrape job boards → fit %, gap %, where to improve | ✅ |
| Dark/light toggle, responsive, animated loading, error handling | ✅ |
| AI: BAAI/bge-small-en-v1.5 embeddings, cosine similarity, demand % = (skill_count/total_jobs)*100, 50/30/20 score | ✅ |
| AI-based skill extraction: BGE embedding similarity + dictionary (detects variants) | ✅ |
| Legal scraping: public only, User-Agent, delay, cache | ✅ |
| LinkedIn-only scraping: India, last 24h, triggered by “Analyze Skills Gap” | ✅ |

---

## Docker (backend)

```bash
cd backend
docker build -t careerfit-ai-api .
docker run -p 8000:8000 --env-file .env careerfit-ai-api
```

---

## Environment

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `EMBEDDING_MODEL` | SentenceTransformer for resume–job similarity. Default: `BAAI/bge-small-en-v1.5` |
| `SCRAPER_DELAY_SECONDS` | e.g. 2 |
| `MAX_UPLOAD_MB` | e.g. 10 |
| `LLM_BASE_URL` | Optional. Local LLM base URL (e.g. `http://localhost:11434` for Ollama). When set, enables AI resume summary and AI advice (gap + match). |
| `LLM_MODEL` | Ollama model name. Default: `llama3.2` |
| `LLM_TIMEOUT_SECONDS` | Timeout for LLM calls. Default: 60 |
| `LLM_PROMPTS_PATH` | Optional. Path to JSON file with prompt templates; see `backend/data/prompts.json`. |
| `USE_EMBEDDING_SKILL_EXTRACTION` | If `true` (default), use BGE embedding similarity in addition to dictionary for skill extraction; detects variants (e.g. "ML" → "Machine Learning"). Set `false` for dictionary-only. |
| `SKILL_EMBEDDING_THRESHOLD` | Min cosine similarity (0.5–1.0) for a phrase to match a dictionary skill when AI extraction is on. Default: 0.72. |
| `USE_SEMANTIC_SKILL_MATCHING` | If `true` (default), matched/missing skills use embedding similarity (e.g. "REST API" ≈ "Backend API development"); set `false` for exact keyword match only. |
| `SEMANTIC_SKILL_MATCH_THRESHOLD` | Min cosine similarity (0.5–1.0) for two skill names to count as a match. Default: 0.8. |

**Resume-gap:** Backend uses fixed **location = India** and **posted_within_hours = 24** for LinkedIn search (not sent from frontend).

**Optional — n8n / custom URL:** **POST /scraper/scrape-search-page** body `{ "url": "https://...", "max_jobs": 30 }` — send a LinkedIn search URL (e.g. from n8n with `f_TPR=r86400`). We parse job links and store jobs.

**Frontend:** optional `VITE_API_URL` (default `/api` for dev proxy).

### Local model and prompts

To enable **AI summary** (on upload) and **AI advice** (after gap analysis and job match), run a local LLM (e.g. [Ollama](https://ollama.com)) and set `LLM_BASE_URL=http://localhost:11434` in `.env`. Install Ollama, then run e.g. `ollama run llama3.2`. Prompts are in `backend/data/prompts.json`; you can override them with `LLM_PROMPTS_PATH`. Keys: `resume_summary`, `gap_advice`, `match_advice`. All prompts are designed for production-style output: **gap_advice** uses the candidate’s **resume excerpt** and **LinkedIn job listings** (sample of 8 jobs from the DB); **match_advice** uses the **resume excerpt** and the **job description** (LinkedIn listing) for the specific role. New resumes get an AI summary stored in `resumes.ai_summary`; gap and match responses include `ai_advice` when the LLM is configured. See [Local LLM & prompts](docs/LOCAL_LLM_AND_PROMPTS.md) for details.
