# AI Job Market Skill Gap Analyzer  
## Undergraduate Thesis Manuscript (Content for ~32 Pages in Word)

**Author:** B. Sai Vignesh  
**Program:** B.Tech, Computer Science and Engineering (Data Science)  
**Institution:** Rajeev Gandhi Memorial College of Engineering & Technology (Autonomous), Nandyal  
**Academic Year:** 2025–2026  
**Supervisors:** Dr. B. Bhaskara Rao; Ms. R. Arshiya  

*This document is written from the implemented repository at `AI Job Market/`. Replace roll numbers, signatures, and any institution-specific boilerplate before binding.*

---

## Certificate (paste college template here)

This is to certify that B. Sai Vignesh has carried out the thesis work entitled **“AI Job Market Skill Gap Analyzer”** based on the full-stack implementation in this repository (FastAPI backend, React frontend, PostgreSQL, optional Redis/ARQ, optional Ollama), under the supervision of the faculty members named on the title page, in partial fulfillment of the requirements for the award of the degree of Bachelor of Technology in Computer Science and Engineering (Data Science).

**Supervisor:** ____________________ **Head of Department:** ____________________  
**External Examiner:** ____________________ **Date:** ____________________

---

## Candidate Declaration

I declare that the technical descriptions, system behavior, limitations, and deployment notes in this thesis reflect the software I implemented and tested. Where published algorithms, models, and libraries are used, they are acknowledged in the References section. I have not copied large passages from internet sources without citation.

**Signature:** ____________________ **Date:** ____________________

---

## Acknowledgement

I thank Dr. B. Bhaskara Rao and Ms. R. Arshiya for supervising this project and for guidance on both the engineering deliverables and the academic framing of results. I thank the department for laboratory access and support. I thank my family and friends for encouragement during integration, deployment, and demonstration rehearsals.

---

## Abstract

Online job descriptions are noisy, synonym-rich, and skill-dense. Candidates preparing for placements need more than keyword highlighting: they need an interpretable map from “what the market is asking for” to “what I should learn next.” This thesis describes **AI Job Market Skill Gap Analyzer**, a full-stack system that ingests resume PDFs, extracts skills, ingests job postings through configurable scrapers, and reports **market fit**, **gap**, **matched and missing skills**, and **high-demand missing skills** using a transparent composite score.

Semantic similarity is computed with **SentenceTransformers** using the pretrained model **`BAAI/bge-small-en-v1.5`**, loaded lazily and reused for performance (`embedding_service.py`). Skills are extracted using **KeyBERT-style** keyphrases combined with dictionary normalization (`data/skills_dictionary.json`) and filtering logic in `skill_service.py`. Resume–job matching combines **semantic**, **skill-overlap**, **keyword**, and **demand-weighted** signals with explicit constants in `match_service.py` (**0.50 / 0.30 / 0.20 / 0.20**, with the demand term applied as a penalty). A **95% confidence interval** is computed for match scores and exposed to the UI.

The backend is **FastAPI + SQLAlchemy async + PostgreSQL**. Optional **Redis** supports an L2 embedding cache and **ARQ** workers (`worker/tasks.py`) for background scraping continuation. Optional **Ollama** integration (`llm_service.py`) provides structured coaching text without requiring a cloud LLM API. The frontend is **React + TypeScript + Vite + Tailwind**, with the main experience in `frontend/src/pages/Dashboard.tsx` and visualization components such as `SkillDemandChart`, `CircularScore`, and `MatchScoreBreakdown`.

The thesis contribution is **applied ML + systems engineering**: integrating pretrained embeddings, robust skill extraction, demand-aware ranking, and deployable infrastructure while stating clear limitations (scraped-sample demand, parser fragility, absence of labeled hiring outcomes).

**Keywords:** skill gap, embeddings, KeyBERT, demand weighting, FastAPI, PostgreSQL, Redis, ARQ, Ollama, React.

---

## Table of Contents (replace with Word auto-TOC)

1. Introduction  
2. Background Concepts and Related Work  
3. Problem Definition, Objectives, and Scope  
4. Requirements and Engineering Constraints  
5. System Architecture and Data Flow  
6. Methodology: Skills, Scraping, Scoring, and Advice  
7. Implementation Mapping (Repository Structure)  
8. Background Jobs, Caching, and Observability  
9. Testing and Validation Plan  
10. Results, Discussion, and Limitations  
11. Conclusion and Future Work  
12. References  
Appendix A — Diagrams and screenshots checklist  
Appendix B — Configuration variables checklist  
Appendix C — Examiner Q&A (repository-grounded)  

---

# Chapter 1 — Introduction

## 1.1 Motivation

Campus hiring preparation is increasingly mediated by online job boards. Students upload resumes, browse postings, and attempt to infer what employers “really want.” Yet many tools reduce this process to **keyword overlap** or a **single similarity score**, neither of which answers the practical question: **which missing skills should I learn first given what employers are posting right now?**

This thesis is motivated by a concrete engineering goal: build a system that (1) reads a resume PDF, (2) extracts skills, (3) collects a slice of job postings relevant to a target role, (4) compares resume skills to market skills, and (5) returns **explainable** outputs: fit percentage, gap percentage, matched skills, missing skills, and **high-demand missing skills** derived from the project’s own database counts.

The repository implements this end-to-end. The README documents the user journey: upload → analyze gap → view jobs → open match modal. The backend stores `Resume`, `ResumeSkill`, `Job`, and `JobSkill` rows in PostgreSQL. Demand percentages are computed from stored jobs, not from external labor-market APIs.

## 1.2 Problem Statement

Three recurring failures in naive resume tools motivate the design:

1. **Lexical mismatch:** employers and candidates describe the same capability using different words. Pure keyword tools fail here.  
2. **Semantic overconfidence:** embeddings can score two texts as similar even when concrete tool requirements differ. Pure embedding tools can fail here.  
3. **Undifferentiated missing skills:** not every missing skill matters equally; missing a skill that appears in many postings should rank higher in a learning plan than missing a rare mention.

The implemented system addresses (1) with **semantic embeddings**, (2) with **explicit skill sets** and overlap logic, and (3) with **demand-aware** treatment of missing skills and a demand penalty in match scoring.

## 1.3 Contributions (what this thesis claims)

This thesis does **not** claim training a new foundation model. The contributions are:

- **System integration:** a deployable pipeline from PDF ingestion to dashboard analytics.  
- **Explainable scoring:** explicit decomposition with documented weights in `match_service.py`.  
- **Operational realism:** Redis/ARQ optional paths, scraping cache windows, LLM timeouts, nginx deployment, structured logging, and `/health` reporting.  
- **Honest demand semantics:** demand is defined as frequency within the **stored posting sample**, not national statistics.

## 1.4 Document roadmap

Chapter 2 summarizes concepts. Chapter 3 formalizes objectives and scope. Chapter 4 states requirements. Chapter 5 presents architecture aligned to `README.md` and `CLAUDE.md`. Chapter 6 explains methodology grounded in services. Chapter 7 maps modules and routes. Chapter 8 discusses workers and caching. Chapter 9 outlines testing. Chapter 10 discusses results and limitations. Chapter 11 concludes.

---

# Chapter 2 — Background Concepts and Related Work

## 2.1 Semantic similarity with sentence embeddings

Transformer-based sentence embeddings map text into dense vectors such that **cosine similarity** approximates semantic closeness for many short-text tasks. This project uses **`BAAI/bge-small-en-v1.5`** via SentenceTransformers, as configured in `backend/app/core/config.py` and implemented in `embedding_service.py` with lazy singleton loading to avoid reloading the model on every request.

## 2.2 Skill extraction: dictionaries, keyphrases, and noise

Skill extraction in industry systems often combines:

- **Dictionary alignment** for canonical skill names. This repository uses `data/skills_dictionary.json`.  
- **Keyphrase extraction** (KeyBERT-style) to propose candidates from free text.  
- **Filtering** to remove implausible spans and boilerplate.

The thesis treats this as a **hybrid NLP pipeline**: statistical proposals plus deterministic normalization.

## 2.3 Explainable multi-signal scoring

Explainable AI in HR-tech often uses weighted sums of interpretable components. This repository follows that pattern: semantic, overlap, keyword, and demand penalty are separable channels, enabling UI breakdown charts (`MatchScoreBreakdown`) and defensible viva explanations.

## 2.4 Demand from postings: what it means scientifically

“Demand” here is an **empirical frequency** within the database: how often a skill appears across stored jobs relative to the corpus size. That definition is methodologically important: it is not a government labor statistic, and it should be communicated that way in defense.

## 2.5 Related deployment patterns

Modern ML services commonly use: an API layer, a worker layer for long jobs, a cache for expensive inference, and observability endpoints. This project’s `CLAUDE.md` documents Prometheus metrics at `/metrics`, Redis embedding cache keys `emb:{sha256}`, and ARQ tasks such as `gap_analysis_task` and `prescrape_jobs`.

---

# Chapter 3 — Problem Definition, Objectives, and Scope

## 3.1 Problem definition

Given a resume PDF and a target role context, estimate **market alignment** and produce **prioritized learning guidance** grounded in recent job postings stored by the system, while providing **transparent** explanations suitable for a student user and academic evaluation.

## 3.2 Objectives

1. Implement authenticated resume ingestion and storage.  
2. Extract skills and store `ResumeSkill` associations.  
3. Scrape and parse job postings, deduplicate via cache policy, store `Job` and `JobSkill`.  
4. Compute gap analytics: fit %, gap %, matched/missing, high-demand missing.  
5. Compute match analytics for a selected job with breakdown + optional CI.  
6. Optional: generate summaries/advice via local Ollama (`llm_service.py`).  
7. Deploy with nginx + systemd on a Linux VM for demonstration.

## 3.3 Scope

**In scope:** PDF parsing (`pdfplumber`), skill pipeline, scrapers and portal registry, match/gap services, dashboard UX, optional Redis/ARQ, optional LLM, log viewer for demos.

**Out of scope:** training a new LLM; proving hiring outcomes with labeled HR datasets; legal compliance certification for scraping at production scale.

---

# Chapter 4 — Requirements and Engineering Constraints

## 4.1 Functional requirements (traceable to routes)

From `README.md` and routers under `backend/app/routers/`:

- **Auth:** register/login and JWT-protected access (`auth.py`, `core/security.py`).  
- **Resumes:** upload PDF, list resumes, optional `POST /resumes/{id}/generate-summary`.  
- **Analysis:** `POST /analysis/resume-gap`, streaming `POST /analysis/resume-gap-stream`, match endpoints, market trends (`GET /analysis/market-trends`), and additional analytics endpoints present in `analysis.py`.  
- **Jobs:** listing and detail views used by the dashboard match modal (`jobs.py`).  
- **Scraper:** operational endpoints for maintenance (`scraper.py`).  
- **Optional ops:** `log_viewer.py` exposes `/logs/*` and `/api/logs/*` when enabled in `main.py`.

## 4.2 Non-functional requirements

- **Security:** bcrypt + JWT; user isolation for resume ownership.  
- **Performance:** lazy embedding model load; Redis embedding cache optional.  
- **Reliability:** ARQ optional; synchronous gap path remains usable when Redis is absent.  
- **Rate limiting:** `slowapi` limiter shared across routers (`core/limiter.py`).  
- **Observability:** request timing middleware, Prometheus `/metrics`, logs.

## 4.3 Ethical and legal constraints (scraping)

Public scraping for academic demos must be framed responsibly: respect rate limits, acknowledge Terms-of-Service constraints, and recommend licensed APIs for production. The thesis should document caching windows (`SCRAPER_CACHE_DAYS`, default 7 per `CLAUDE.md`) as a politeness and stability measure, not as a claim of legal authorization.

---

# Chapter 5 — System Architecture and Data Flow

## 5.1 Client and edge routing

The frontend is a React SPA (`frontend/`) routed via `frontend/src/App.tsx` with a landing page and a dashboard route under `/app`. In development, Vite proxies `/api` to the backend. In production, **nginx** serves static build artifacts and proxies `/api` to Uvicorn.

This split matters: FastAPI routes are rooted at `/resumes`, `/analysis`, etc., while the browser calls `/api/...` through the proxy.

## 5.2 Backend application layer

`backend/app/main.py` constructs the FastAPI app, applies middleware (CORS, request timing), initializes Redis and ARQ when possible, and includes routers:

- `auth_router`  
- `jobs.router`  
- `resume_router.router`  
- `analysis.router`  
- `scraper.router`  
- `log_viewer_router` mounted twice: `/logs/*` and `/api/logs/*` to support different nginx forwarding behaviors.

## 5.3 Core services (business logic)

`CLAUDE.md` lists the primary services:

- `embedding_service.py` — BGE singleton  
- `skill_service.py` — KeyBERT + dictionary + demand computations  
- `match_service.py` — composite scoring + CI  
- `scraper_service.py` — LinkedIn flow (India, last 24h defaults in README)  
- `resume_service.py` — PDF text extraction  
- `llm_service.py` — optional Ollama `/api/generate`  
- `gap_service.py` — orchestrates gap pipeline including scrape stages  

## 5.4 Persistence and analytics tables

PostgreSQL stores normalized skills and many-to-many join tables for resume and job skills. Additional models imported in `main.py` support career analytics and feedback features; these demonstrate extensibility beyond the core gap story.

## 5.5 External dependencies

- **LinkedIn** public search and job pages (HTML parsing).  
- **Hugging Face** model download for BGE on first use.  
- **Ollama** optional local inference.

## 5.6 Primary user flows (repository-accurate)

**Upload:** `POST /resumes/upload` → pdfplumber text → skill extraction → `Resume` + `ResumeSkill`.

**Gap analysis:** `POST /analysis/resume-gap` → `GapAnalysisService.analyze` → ensure skills → scrape via `ScraperService.scrape_quick` (bounded immediate work) → may enqueue `background_scrape_task` when ARQ pool exists → compute gap output → optional LLM advice.

**Streaming:** `POST /analysis/resume-gap-stream` emits SSE progress events for long runs.

**Match:** `GET /analysis/match` → embeddings + overlap + keyword + demand penalty + optional LLM advice.

---

# Chapter 6 — Methodology

## 6.1 Skill extraction methodology

The pipeline converts resume/job text into candidate skills, then normalizes to dictionary entries where possible. Blocklists and plausibility heuristics reduce “skills” that are sentence fragments. Configuration toggles (`USE_EMBEDDING_SKILL_EXTRACTION`, `USE_SEMANTIC_SKILL_MATCHING`) allow optional embedding-assisted matching against dictionary phrases for unseen variants.

## 6.2 Scraping methodology

The LinkedIn adapter under `portals/` builds search URLs from skill terms and configured location/time filters (README: India, last 24 hours). HTML parsing extracts listing links and job detail pages. Jobs are deduplicated using `external_id` hashing with a cache window (`SCRAPER_CACHE_DAYS`).

`GapAnalysisService` uses `scrape_quick` with `max_quick` to return partial results quickly while optionally handing remaining URLs to ARQ for best-effort continuation—an engineering response to HTTP latency limits.

## 6.3 Gap computation methodology

Gap compares resume skills to the union of skills observed across stored jobs for the relevant slice. Fit and gap percentages summarize coverage. High-demand missing skills rank missing items by frequency in the corpus.

## 6.4 Match scoring methodology

Match scoring uses:

\[
\text{Score} = 0.50\,S + 0.30\,O + 0.20\,K - 0.20\,D
\]

where \(D\) reflects demand-weighted missing skills (README: demand penalty uses average demand % of missing skills). Constants are defined in `match_service.py` as `WEIGHT_SEMANTIC`, `WEIGHT_SKILL_OVERLAP`, `WEIGHT_KEYWORD`, `WEIGHT_DEMAND_PENALTY`.

## 6.5 Optional LLM methodology

If `LLM_BASE_URL` is set, `llm_service.py` posts to Ollama `/api/generate` with prompts from `data/prompts.json` or built-in templates. JSON-structured advice paths attempt to parse model output into UI-friendly structures, with fallback when parsing fails. `LLM_TIMEOUT_SECONDS` must be tuned on CPU-only hosts to avoid read timeouts.

---

# Chapter 7 — Implementation Mapping

## 7.1 Routers as HTTP boundaries

Routers should remain thin: validate inputs, call services, return schemas. `analysis.py` includes rate limits on expensive endpoints (e.g., gap endpoints limited to `1/10 seconds` in the current file), protecting public demos from accidental abuse.

## 7.2 Schemas and models

`app/schemas/` defines API contracts such as gap and match outputs. `app/models/` defines ORM entities. This separation prevents leaking internal columns and supports stable API evolution.

## 7.3 Match service responsibilities

`match_service.py` centralizes scoring logic and explanatory strings used by the UI. It also includes defensive sanitization for misleading extremes when markets are sparse or resumes are unusually broad (see `_sanitize_gap_fit` logic in the file).

## 7.4 Gap service responsibilities

`gap_service.py` coordinates multi-step analysis, progress callbacks for SSE, scraping locks/freshness behavior, and optional ARQ enqueue for background scraping continuation.

## 7.5 Worker tasks

`worker/tasks.py` defines `gap_analysis_task` (full gap analysis in worker), `prescrape_jobs` (cron-style warm-up), and `background_scrape_task`. Worker startup initializes DB session factory, Redis, and an ARQ pool for enqueueing follow-ups.

## 7.6 Frontend mapping

`Dashboard.tsx` orchestrates user actions. Components like `GapAdviceStructured` and `MatchAdviceStructured` render LLM structured output when present. `SkillDemandChart` renders demand visualization using Recharts.

---

# Chapter 8 — Background Jobs, Caching, and Observability

## 8.1 Redis and graceful degradation

If Redis cannot connect, the app logs degradation and continues with synchronous paths where possible (`CLAUDE.md` describes graceful degradation). This is essential for student laptops without Docker services running.

## 8.2 Embedding cache

Redis stores embedding cache entries with TTL (24h) and key `emb:{sha256}` (`CLAUDE.md`). This reduces repeated CPU work for identical text inputs.

## 8.3 Prometheus and logs

`/metrics` supports instrumentation. Request timing middleware logs method, path, status, and duration. For VM demos, `journalctl` for the systemd unit complements application logs. Optional `LOG_FILE_PATH` enables file logging and the HTTP log viewer for judges on Wi‑Fi.

---

# Chapter 9 — Testing and Validation

## 9.1 Automated tests

Tests live in `backend/tests/` and run with `uv run pytest` (`CLAUDE.md`). Tests should cover scoring edge cases, parsing failures, and critical API contracts where implemented.

## 9.2 Manual end-to-end scenarios

Recommended demo scripts:

1. Fresh DB migrate → upload resume → verify skills list.  
2. Run gap analysis → verify jobs inserted → verify fit/gap and demand chart.  
3. Open match modal → verify breakdown sums align with documented weights.  
4. Disable Redis → verify gap still returns.  
5. Enable Ollama → verify advice appears; tune timeout if needed.

## 9.3 Performance checks

Record cold-start embedding latency, warm latency, and LLM latency under CPU-only conditions. Include tables in the final bound thesis.

---

# Chapter 10 — Results, Discussion, and Limitations

## 10.1 Qualitative results

The system produces coherent dashboards for typical engineering resumes when the job corpus is non-empty. Explainable breakdowns support academic defense because examiners can tie numbers to code constants.

## 10.2 Limitations

- Demand is **sample-defined** (posting corpus), not universal.  
- Scraping parsers are **brittle** to HTML changes.  
- LLM latency and hallucination risk on small models.  
- No labeled hiring outcomes → no hiring-accuracy claim.

## 10.3 Threats to validity

Geography and portal selection bias results. Short time windows (24h) bias toward immediate postings. These must be stated explicitly.

---

# Chapter 11 — Conclusion and Future Work

The project delivers a credible capstone system combining pretrained embeddings, robust skill extraction, demand-aware ranking, and deployable full-stack engineering. Future work: multi-source ingestion, labeled evaluation sets, weight sensitivity analysis, fairness reporting, multilingual support, and stronger compliance posture for scraping.

---

# Chapter 12 — References (expand to IEEE/APA as required)

1. Reimers & Gurevych, Sentence-BERT (2019).  
2. BAAI `bge-small-en-v1.5` model card (Hugging Face).  
3. KeyBERT (Grootendorst).  
4. FastAPI documentation.  
5. SQLAlchemy async documentation.  
6. PostgreSQL documentation.  
7. Redis documentation.  
8. ARQ documentation.  
9. Ollama documentation.  
10. pdfplumber documentation.  
11. Project `README.md` and `CLAUDE.md` (implementation facts).

---

## Appendix A — Figures and screenshots checklist

- Architecture diagram (ecosystem flow).  
- Screenshot: Landing page.  
- Screenshot: Dashboard upload success.  
- Screenshot: Gap results (fit/gap, charts).  
- Screenshot: Match modal breakdown.  
- Screenshot: Swagger `/docs`.  
- Screenshot: `/health` JSON.  
- Screenshot: `journalctl` excerpt (VM).

---

## Appendix B — Configuration checklist (from `config.py` / `.env.example`)

Document in the final thesis with exact values you used:

- `DATABASE_URL`  
- `EMBEDDING_MODEL`  
- `SIMILARITY_THRESHOLD`, `SKILL_SIMILARITY_THRESHOLD`, `SEMANTIC_MATCH_THRESHOLD`  
- `SCRAPER_CACHE_DAYS`, `SCRAPER_DELAY`, time/location defaults as deployed  
- `REDIS_URL` (empty vs set)  
- `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`  
- `JWT_SECRET_KEY` rotation for production  
- `LOG_VIEWER_*` and `LOG_FILE_PATH` (demo only)

---

## Appendix C — Examiner Q&A (repository-grounded)

**Q:** Why both embeddings and keywords?  
**A:** Embeddings handle paraphrase; keywords reflect ATS-style lexical signals; both appear as explicit channels in the match decomposition.

**Q:** What is “demand” in your system?  
**A:** Frequency of a skill across stored `JobSkill` rows for the current corpus slice, expressed as a percentage; not a national labor statistic.

**Q:** Where are weights defined?  
**A:** `match_service.py` constants `WEIGHT_SEMANTIC`, `WEIGHT_SKILL_OVERLAP`, `WEIGHT_KEYWORD`, `WEIGHT_DEMAND_PENALTY`.

**Q:** What happens if Redis is down?  
**A:** ARQ may be disabled; gap analysis can still run synchronously per `CLAUDE.md` graceful degradation narrative and `/health` reporting.

**Q:** Why streaming gap endpoint?  
**A:** `POST /analysis/resume-gap-stream` provides SSE progress for long scrape/embed phases.

**Q:** How are jobs deduplicated?  
**A:** External id hashing with `SCRAPER_CACHE_DAYS` cache window.

**Q:** What model is used for embeddings?  
**A:** `BAAI/bge-small-en-v1.5` via SentenceTransformers.

**Q:** Is the LLM required?  
**A:** No. Set `LLM_BASE_URL` empty to disable; numeric pipeline remains.

**Q:** What is your deployment edge?  
**A:** nginx serves SPA and proxies `/api` to Uvicorn; systemd manages API process on VM.

---

## Appendix D — Extended narrative: gap analysis execution path (for page volume + clarity)

This appendix expands the **exact** runtime story of gap analysis as implemented, without repeating generic “AI will change the world” language. It is meant to be pasted after core chapters if you need additional pages, while staying faithful to the repository.

When the user triggers gap analysis, the backend first ensures the resume exists and that resume skills are materialized. This “ensure skills” step matters because students often upload PDFs with formatting that causes imperfect initial extraction; the service layer retries extraction logic and persists normalized associations before attempting market comparison.

The scraper stage is intentionally split into a quick synchronous batch and an optional asynchronous remainder. The engineering reason is straightforward: HTTP requests should not block for unbounded network fan-out. By bounding immediate fetches, the system returns partial market evidence quickly, then continues ingestion in the background when ARQ is available. If ARQ is unavailable, the remainder may be dropped with warnings logged, which is a honesty point for the thesis: background continuation is best-effort, not guaranteed.

Once jobs exist in the database, demand statistics become computable as simple SQL-friendly aggregates over `JobSkill`. This is why the demand signal is reproducible: it is derived from the same tables the UI queries, not from a hidden external service.

The match workflow reuses embeddings and structured skills but optimizes for a different question: “How well does this candidate fit **this specific posting**?” That shift changes interpretation: gap analysis is market-wide relative to a role slice, while match analysis is pairwise. The UI communicates this distinction by presenting a modal with a per-job score and breakdown.

Optional LLM advice is generated only after structured inputs are assembled: resume excerpts and job description text. When timeouts occur on CPU-only servers, the thesis should report the mitigation path: increase `LLM_TIMEOUT_SECONDS`, warm models, or disable LLM for quantitative-only demos. This is not a footnote; it is a core lesson in deploying local inference next to traditional web services.

Observability ties the story together: Prometheus metrics and structured logs allow you to prove the system executed real requests during evaluation. For a thesis defense, you should be prepared to show `/metrics` and a log line correlating a gap request with duration milliseconds.

Finally, reproducibility should include Alembic migrations and exact dependency installation via `uv`. A reviewer should be able to recreate your environment with documented commands and reach the same API behavior on a sample resume PDF included in the appendix.

---

## Appendix E — Extended narrative: security, multi-user isolation, and abuse controls

Authentication exists because resumes are sensitive. JWT-based access prevents arbitrary users from downloading another user’s resume artifacts. bcrypt password hashing reduces risk if the database is compromised. In the thesis, connect these mechanisms explicitly to privacy requirements stated in Chapter 4.

Rate limiting is not merely “best practice”; it is part of making a public demo survivable. Gap analysis triggers scraping and embedding work; allowing unlimited requests could overload a small VM. The repository applies `slowapi` limits on selected endpoints; cite the exact limit expressions from `analysis.py` in your final bound copy after verifying them in your branch.

CORS configuration is another deployment-sensitive area: browsers enforce CORS strictly when credentials are used. The backend configuration uses explicit allowed origins rather than insecure wildcard patterns for credentialed requests (`CLAUDE.md` notes this). In writing, explain why this matters for a student demo accessed from a known frontend origin.

The optional log viewer is a demonstration feature with security implications. It should be disabled after public exposure, tokens rotated, and access restricted. The thesis should treat this as operational security hygiene rather than as a core scientific contribution.

---

## Appendix F — Extended narrative: frontend UX evidence and evaluation

The dashboard is the scientific instrument through which examiners experience your claims. Therefore, the thesis should describe not only backend metrics but also how the UI proves interpretability: breakdown charts, lists, and structured advice panels.

The match modal is particularly important because it shows each score component side-by-side with matched and missing skills. That presentation supports the thesis argument that the system is explainable: users can see which channel dominates.

Market trend views, when demonstrated, show that the project thinks beyond a single snapshot analysis. Even if trends are not the primary research claim, they demonstrate time-aware analytics built on `Job.created_at` timestamps.

For evaluation, include a table of scenarios: sparse corpus, rich corpus, LLM enabled/disabled, Redis enabled/disabled. For each scenario record observed latency and qualitative correctness. This is stronger than repeating adjectives about “good performance.”

---

## Appendix G — Glossary (short, for clarity)

- **Corpus slice:** jobs stored in PostgreSQL after scraping within configured filters.  
- **Fit % / gap %:** summary metrics derived from resume vs market skill coverage (see README).  
- **High-demand missing:** missing skills ranked by frequency in the corpus.  
- **ARQ:** async task queue system used with Redis in this project.  
- **SSE:** server-sent events streaming for long-running gap analysis.

---

## Notes on reaching ~32 pages in Microsoft Word

1. Use **Times New Roman 12 pt**, **1.5 line spacing**, standard margins.  
2. Insert your college **title page, certificate, and declaration** before Chapter 1.  
3. Convert headings to Word **Heading 1/2/3** styles and generate an **automatic Table of Contents**.  
4. Paste screenshots into Appendices; each full-page figure adds ~1 page.  
5. The **Part II** section below adds repository-specific depth; combine with 8–12 screenshot pages to reach ~32 pages total.

---

# Part II — Additional thesis body (repository-specific depth)

## II.1 Component catalog: backend services you should name in viva

The repository’s core intelligence is concentrated in `backend/app/services/`. Each module has a distinct responsibility, and the thesis should explain them as cooperating services rather than as one monolithic script.

`embedding_service.py` owns model lifecycle and encoding. Because transformer inference is expensive, the service is structured so the model loads once and is reused. In writing, emphasize **latency** and **memory**: a capstone VM has finite RAM, and embedding batching choices affect whether the API remains responsive under concurrent users.

`skill_service.py` owns extraction, dictionary alignment, demand aggregation, and many defensive filters. This is where much of the “data cleaning” story lives: the difference between a demo that looks intelligent and one that shows nonsense skills is largely normalization quality. The thesis should mention `skills_dictionary.json` explicitly as the canonical vocabulary anchor.

`resume_service.py` owns PDF ingestion using pdfplumber. PDF resumes vary widely: multi-column layouts, icons, and embedded fonts can degrade text extraction. The thesis should acknowledge extraction errors as a limitation and describe mitigations you used (manual re-upload, trimming, or improving parsing rules).

`scraper_service.py` owns network ingestion and HTML parsing. This is inherently fragile: job boards change markup. The thesis should document what you observed during development (for example, occasional parse misses) and how caching reduced repeated failures during iterative testing.

`match_service.py` owns scoring and explanatory breakdown generation. This file is the scientific “equation page” of the thesis: weights, penalties, and confidence intervals should be explained with direct reference to constants and helper functions.

`gap_service.py` owns orchestration: skill readiness, scraping stages, optional ARQ enqueue, and returning a coherent `ResumeGapOut` payload. This module is where the “system story” becomes sequential: it is the narrative backbone for Chapter 6.

`llm_service.py` owns optional local inference. The thesis should treat LLM outputs as **presentation-layer assistance** unless you formally evaluate advice quality. Quantitative scoring remains defined without LLM.

## II.2 Router catalog: what each HTTP surface proves

Routers under `backend/app/routers/` define the externally visible contract of the system.

`auth.py` proves multi-user isolation: the project is not a toy single-user script. JWT-based access is a standard engineering choice; the thesis should connect it to privacy.

`resume.py` proves ingestion and optional summary generation. Upload endpoints must validate file types and sizes; the thesis can mention configuration caps from `config.py` (for example max upload MB).

`analysis.py` proves analytics breadth: gap, streaming gap, match, trends, and other endpoints compiled in the router file. For a strong thesis chapter, pick **three** endpoints and explain request payloads, response schemas, and failure codes.

`jobs.py` proves the job browsing experience needed for match selection.

`scraper.py` proves operational maintenance hooks for scraping workflows.

`log_viewer.py` proves demo observability. If used, document security controls (`LOG_VIEWER_TOKEN`) and post-demo disable steps.

## II.3 Data model narrative: why relational design matters

PostgreSQL is chosen because the project’s core entities are relational: users own resumes; resumes have many skills; jobs have many skills; timestamps support trend queries. A document-only database could work, but SQL simplifies demand aggregation and join queries that power charts.

The thesis should include a **logical ER description** in words: `User` → `Resume` → `ResumeSkill` → `Skill`; `Job` → `JobSkill` → `Skill`. Even without a formal diagram tool, a paragraph-level ER description adds pages and clarity.

## II.4 Demand computation: a worked example (examiners like numbers)

Suppose the database contains 200 jobs after scraping and the skill “Docker” appears in 60 job skill rows. A naive demand percentage can be described as \(60/200 = 30\%\) within that corpus. The thesis should walk through one example like this, then immediately qualify: if the corpus is actually 12 jobs because scraping returned few results, the percentage is unstable.

This is how you defend honesty: show the formula on a toy dataset, then show the same formula on a sparse dataset and discuss instability.

## II.5 Match scoring: connect formula to UI fields

The README states match scoring uses semantic similarity, overlap, keyword coverage, and a demand penalty based on missing skills’ demand percentages, with a 95% CI. In the thesis, create a table:

| Component | Meaning | Typical UI location |
|---|---|---|
| Semantic | embedding cosine similarity between resume and job text | match modal breakdown |
| Overlap | intersection of normalized skill sets | matched skills list |
| Keyword | lexical coverage signal | breakdown bar |
| Demand penalty | missing high-frequency skills reduce score | explanation text |

Then explain one example: if overlap is high but demand penalty is high, the candidate is “narratively close” but missing market-common tools.

## II.6 Gap vs match: two questions, two pipelines

Gap answers: “How much of the current market skill set do I cover?”  
Match answers: “How strong is my fit for this one posting?”

The thesis should keep these separate because examiners will ask. The implementation uses different orchestration (`gap_service.py` vs match paths in `match_service.py`) and different UI surfaces (dashboard panels vs modal).

## II.7 Background jobs: `gap_analysis_task` vs inline gap

`worker/tasks.py` defines `gap_analysis_task` which runs `GapAnalysisService.analyze` inside a worker DB session. The thesis should explain why workers exist: long CPU/network work should not pin API workers indefinitely.

Also describe `prescrape_jobs`: a cron-style warm-up task referenced in project documentation that keeps the database “warm” so interactive gap requests are less likely to block on cold scraping.

## II.8 Caching: embeddings and job deduplication

Two caches matter narratively:

1. **Embedding cache** in Redis with TTL ~24h (`emb:{sha256}` keys).  
2. **Job deduplication** across days using `SCRAPER_CACHE_DAYS`.

Explain each with a user-visible effect: faster repeated analysis; fewer duplicate job rows.

## II.9 Frontend architecture: components as evidence

The dashboard is not cosmetic; it is the proof of explainability.

`CircularScore` communicates a headline metric quickly.  
`SkillDemandChart` communicates market frequency visually.  
`MatchScoreBreakdown` communicates the decomposition thesis claim.  
`GapAdviceStructured` / `MatchAdviceStructured` communicate optional LLM structuring.

The thesis should include screenshots of each with captions that reference the JSON fields returned by the backend.

## II.10 Deployment narrative: nginx + systemd + environment

Describe the VM stack you used: public IP, nginx serving `frontend/dist`, proxy `/api` to Uvicorn, PostgreSQL service, optional Redis, optional Ollama as a systemd service.

Include commands you actually ran (sanitized): `sudo systemctl restart ai-job-market-api`, `sudo journalctl -u ...`, `curl http://127.0.0.1:8000/health`.

## II.11 Failure modes you should document (credibility)

1. **Ollama ReadTimeout** on CPU-only hosts: tie to `LLM_TIMEOUT_SECONDS`.  
2. **404 on `/api/logs/watch`**: tie to nginx path prefix and dual-mount fix in `main.py` if that was part of your deployment story.  
3. **Sparse scrape results**: tie to market window and HTML fragility.  
4. **Over-broad resume skills**: tie to extraction noise and filters.

## II.12 Testing matrix (fill with your measured results)

| Scenario | Redis | LLM | Expected | Observed | Notes |
|---|---:|---:|---|---|---|
| Upload PDF | off | off | skills saved |  |  |
| Gap analysis | off | off | jobs + gap |  |  |
| Gap analysis | on | off | quicker repeat |  | embedding cache |
| Gap stream | on | off | SSE events |  |  |
| Match modal | off | off | breakdown |  |  |
| Match modal | on | on | advice text |  | timeouts? |

## II.13 Future work: credible research extensions

1. Labeled dataset of “relevant/not relevant” job pairs for match evaluation.  
2. Weight sensitivity grid search with held-out validation.  
3. Multi-portal ingestion with unbiased demand estimation.  
4. Fairness auditing by geography and gendered language proxies (where ethical review exists).  
5. Multilingual resumes and postings.

## II.14 Academic positioning: “integration thesis” paragraph (use verbatim if helpful)

This project’s novelty is not a new transformer architecture. It is the **integration** of pretrained embeddings, robust skill extraction, demand-aware ranking, optional local LLM assistance, and production-style deployment into a single coherent system with explicit limitations and measurable operational behavior.

## II.15 Long-form paragraph: how scraping interacts with skill demand

Scraping determines which job descriptions enter PostgreSQL. Skill extraction then determines which skills attach to each job row. Demand percentages are computed over the resulting `JobSkill` graph. Therefore, demand is jointly shaped by scraper coverage, parser correctness, and skill normalization. Any thesis claiming “market demand” without stating those dependencies would be overstating. This paragraph is intentionally methodological: it tells the examiner you understand the full pipeline sensitivity chain.

## II.16 Long-form paragraph: why PostgreSQL supports analytics queries

Trend endpoints aggregate by time windows on `Job.created_at`. Relational indexing on timestamps and foreign keys makes these queries feasible as the corpus grows. A thesis section describing indexing choices (even if you did not add exotic indexes) shows database maturity.

## II.17 Long-form paragraph: why async SQLAlchemy matters here

The system performs network I/O (scraping), CPU-heavy inference (embeddings), and DB I/O. Async endpoints allow the server to interleave waiting periods rather than blocking threads naively. This is a standard FastAPI benefit and belongs in an engineering thesis.

## II.18 Long-form paragraph: Prometheus and `/health` as “operational proofs”

Prometheus metrics and `/health` JSON are not user features, but they are thesis features: they demonstrate you built a service, not a notebook. Include screenshots and interpret fields like redis connected/disabled.

## II.19 Long-form paragraph: README as the behavioral specification

For this repository, `README.md` is the closest document to a behavioral spec: it enumerates user actions and backend responses. In academic writing, treat it as a companion artifact: not a citation replacement, but a map from claims to reproducible steps.

## II.20 Long-form paragraph: `CLAUDE.md` as the architecture spec

`CLAUDE.md` summarizes modules, env vars, and infra. Use it to ensure your thesis names match the repository naming (`GapAnalysisService`, `ScraperService`, etc.). Consistency reduces suspicion of generic AI text.

## II.21 Long-form paragraph: what you should NOT claim

Do not claim national hiring probability, GDPR compliance without evidence, or scraping legality beyond academic scope. Those claims invite cross-examination failures.

## II.22 Long-form paragraph: how to present limitations as strengths

A limitation stated precisely (sample-defined demand) is stronger than a vague claim of “real-time global labor data.” Examiners reward epistemic clarity.

## II.23 Long-form paragraph: reproducibility checklist for appendix

Include: Python version, `uv sync` lockfile note, DB name `ai_resume_analyzer`, migration command, embedding model download time, minimum RAM observed, and disk space after model download.

## II.24 Long-form paragraph: evaluation ethics for scraped data

Discuss consent, robots.txt, rate limits, and respectful caching. Even short ethical discussion improves thesis tone.

## II.25 Closing instructions for binding

Print double-sided only if your college allows; otherwise single-sided. Include signed certificate pages. Staple or spiral-bind per department rules.

---

# Part III — API inventory and service map (accurate to this repository)

## III.1 Analysis router (`/analysis` prefix in API)

The following routes are defined in `backend/app/routers/analysis.py` (paths are relative to the analysis router’s mount; in deployment they appear under `/api/analysis/...` when the app mounts the router accordingly—verify your `main.py` include prefix when writing the exact URL list in the bound thesis).

| Method | Path | Role in thesis narrative |
|--------|------|----------------------------|
| GET | `/match` | Pairwise resume–job scoring with breakdown |
| GET | `/skill-demand` | Demand chart data for skills |
| GET | `/suggest-roles` | Role suggestions from structured signals |
| POST | `/simulate-skills` | Counterfactual “what if I add skills?” |
| POST | `/job-feedback` | User feedback loop for intelligence layer |
| GET | `/skill-trends` | Time-window skill trend engine output |
| GET | `/career-path` | Path-style recommendations |
| GET | `/global-insights` | Aggregated cross-user insights (document access controls) |
| GET | `/career-trajectory` | Trajectory modeling output |
| GET | `/career-progress` | Progress-style summary metrics |
| GET | `/market-trends` | Market trend panels |
| POST | `/resume-gap` | Core gap analysis (queue or inline per infra) |
| POST | `/resume-gap-stream` | SSE streaming gap analysis |
| GET | `/status/{task_id}` | Poll async gap task status |

For defense, pick **five** routes and be able to describe input schema fields and one example JSON response shape without reading from notes.

## III.2 Resume, jobs, auth, scraper, logs

**Auth (`auth.py`):** `POST /register`, `POST /login`, `GET /me`.  
**Resumes (`resume.py`):** list resumes, `POST /upload`, `POST /{id}/generate-summary`, `GET /{id}/suggest-roles`, `GET /{id}` analysis payload.  
**Jobs (`jobs.py`):** list jobs, `GET /{job_id}` detail.  
**Scraper (`scraper.py`):** `POST /scrape-search-page`, `POST /scrape`.  
**Log viewer (`log_viewer.py`):** two GET endpoints for demo log streaming (treat as optional and security-sensitive).

## III.3 Services directory: full module list

Beyond the “core six” services, the repository includes additional analytics modules you can describe as **extensions** rather than pretending every path is equally central:

`career_progress_service.py`, `career_path_service.py`, `career_stats_service.py`, `trajectory_service.py`, `role_fit_service.py`, `role_graph_service.py`, `global_intel_service.py`, `feedback_intelligence_service.py`, `decision_engine_service.py`, `skill_cluster_service.py`, `job_corpus_service.py`, `user_profile_service.py`, `confidence_service.py`, `scrape_cache.py`, `job_search_cache.py`, `live_job_registry.py`, `live_resume_registry.py`, `normalization.py`, `skill_normalizer.py`, `adzuna_service.py`, portal plugins under `portals/` (`base.py`, `linkedin.py`, `registry.py`).

The thesis can use a tiered story:

- **Tier A (core):** embeddings, skills, match, gap, resume PDF, scraper.  
- **Tier B (product depth):** career/trajectory/global insights endpoints.  
- **Tier C (infra):** caches, registries, confidence helpers.

This tiering prevents the document from reading like a directory dump while still proving you know the codebase.

## III.4 Portal plugin system

`portals/registry.py` and `portals/linkedin.py` implement a plugin-style boundary for job sources. The thesis should explain why plugins matter: swapping adapters (LinkedIn vs Adzuna) isolates HTML quirks from core analytics.

## III.5 Confidence intervals

`confidence_service.py` exists as a dedicated module; tie it to the README claim of **95% CI** on match scoring. Explain at a high level: uncertainty arises from finite text and component noise; CI communicates range, not oracle truth.

## III.6 Feedback loop

`/job-feedback` and `feedback_intelligence_service.py` support learning from user actions. Even if evaluation is limited, describe intended behavior: store feedback, adjust future suggestions or reporting.

## III.7 Caches beyond Redis embeddings

`scrape_cache.py` and `job_search_cache.py` reduce repeated network load. Mention them when discussing polite scraping and demo stability.

## III.8 Live registries

`live_job_registry.py` and `live_resume_registry.py` support in-memory or fast lookup patterns used by streaming or live UI paths. If you used SSE streaming, connect these modules to “keeping partial state while events flow.”

## III.9 Skill clustering

`skill_cluster_service.py` supports grouping skills for visualization or summarization. If the UI shows clusters, screenshot and reference; if not used in your demo, mention as optional extension.

## III.10 Decision engine

`decision_engine_service.py` centralizes some policy-like decisions (thresholding, routing, or ranking). Describe it as the place where “business rules” meet ML outputs—useful for viva questions about why a score changed after a config tweak.

## III.11 Adzuna adapter

`adzuna_service.py` is an alternative job board adapter. Compare to LinkedIn portal: different API constraints, different bias. This supports a “data source bias” discussion.

## III.12 Global insights caveat

`global_insights` endpoints may aggregate across users. The thesis must state **privacy controls**: what is aggregated, whether PII is excluded, and why public demos should disable or restrict such endpoints.

## III.13 Extended limitations paragraph (unique)

The system’s outputs are conditional on the scraped corpus, dictionary coverage, PDF extraction quality, embedding model choice, and configured weights. Changing any one factor can reorder “top missing skills” or match rankings. Therefore, the correct scientific statement is: **the system computes consistent scores relative to its configured pipeline**, not absolute labor-market truth. That single sentence, expanded into a half-page discussion with two numeric toy examples, is high-quality thesis content because it demonstrates statistical maturity.

## III.14 Extended “related work” glue (non-plagiarized)

Traditional ATS keyword matching fails on synonymy and context; dense retrieval improves semantic recall but may miss structured skill constraints; structured taxonomies improve comparability but require maintenance. This project hybridizes: embeddings for semantic channel, normalized skills for overlap channel, dictionary-backed demand for market channel, optional LLM for narrative explanation. That paragraph positions the engineering without copying papers.

## III.15 What to screenshot (minimum set)

1. Landing page.  
2. Dashboard upload success + skill list.  
3. Gap analysis result with fit/gap and missing skills.  
4. Skill demand chart.  
5. Match modal with breakdown + CI if shown.  
6. Market trends view.  
7. `/health` JSON.  
8. `/metrics` excerpt.  
9. ARQ worker log line (if used).  
10. nginx site config snippet (redact secrets).

## III.16 Glossary additions

- **Tier A/B/C:** thesis-defined grouping of modules by centrality.  
- **SSE:** server-sent events for progressive gap updates.  
- **Plugin portal:** scraper adapter implementing a shared interface.  
- **Corpus-defined demand:** demand derived only from ingested jobs.

---

*End of manuscript content file.*
