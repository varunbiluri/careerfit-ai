#!/usr/bin/env python3
"""
Build thesis DOCX: project-specific prose (AI Job Market repo), minimal repetition.
Output: THESIS_SUBMISSION_32_PAGES.docx at repo root.
Requires: python-docx (.tools-venv)
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THESIS_SUBMISSION_32_PAGES.docx"
IMG = (
    Path.home()
    / ".cursor"
    / "projects"
    / "Users-varunbilluri-AI-Job-Market"
    / "assets"
    / "Job_Scraper_Ecosystem_Flow-2026-04-13-044631.png"
)


def setup(doc: Document) -> None:
    s = doc.sections[0]
    s.top_margin = Inches(1)
    s.bottom_margin = Inches(1)
    s.left_margin = Inches(1.25)
    s.right_margin = Inches(1)
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)


def p(
    doc: Document,
    text: str,
    *,
    bold: bool = False,
    size: int = 12,
    align=WD_PARAGRAPH_ALIGNMENT.JUSTIFY,
    after: int = 6,
) -> None:
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.bold = bold
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    para.paragraph_format.line_spacing = 1.5
    para.paragraph_format.space_after = Pt(after)
    para.alignment = align


def chapter(doc: Document, title: str) -> None:
    doc.add_page_break()
    p(doc, title, bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.LEFT)
    p(doc, "")


def main() -> None:
    doc = Document()
    setup(doc)

    # --- Title / meta ---
    p(
        doc,
        "UNDERGRADUATE THESIS",
        bold=True,
        size=16,
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(
        doc,
        "AI Job Market Skill Gap Analyzer",
        bold=True,
        size=15,
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(
        doc,
        "Explainable resume–job skill gap analysis using BGE embeddings, KeyBERT-style "
        "skill extraction, demand-weighted scoring, and a FastAPI + React full-stack "
        "deployment with optional Ollama assistance.",
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(doc, "")
    p(
        doc,
        "Submitted by B. Sai Vignesh  Roll No: ____________________",
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(
        doc,
        "Supervisors: Dr. B. Bhaskara Rao; Ms. R. Arshiya",
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(
        doc,
        "Department of Computer Science and Engineering (Data Science), "
        "Rajeev Gandhi Memorial College of Engineering & Technology (Autonomous), Nandyal",
        align=WD_PARAGRAPH_ALIGNMENT.CENTER,
    )
    p(doc, "Academic Year: 2025–2026", bold=True, align=WD_PARAGRAPH_ALIGNMENT.CENTER)

    doc.add_page_break()
    p(doc, "CERTIFICATE", bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.CENTER)
    p(
        doc,
        "This is to certify that B. Sai Vignesh has completed the thesis work entitled "
        "“AI Job Market Skill Gap Analyzer” based on the implemented codebase in this "
        "repository: a FastAPI backend under `backend/app/`, a React + TypeScript frontend "
        "under `frontend/src/`, PostgreSQL persistence, optional Redis and ARQ workers, and "
        "nginx-based production deployment. The work is submitted in partial fulfillment of "
        "the B.Tech (CSE Data Science) requirements for 2025–2026.",
    )
    p(doc, "Supervisor: ____________________  HOD: ____________________")
    p(doc, "External Examiner: ____________________  Date: ____________________")

    doc.add_page_break()
    p(doc, "DECLARATION", bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.CENTER)
    p(
        doc,
        "I declare that the descriptions of architecture, APIs, scoring, and deployment "
        "reflect the system I implemented and tested. External libraries (SentenceTransformers, "
        "FastAPI, etc.) are used under their licenses and are cited in the references.",
    )
    p(doc, "Signature: ____________________  Date: ____________________")

    doc.add_page_break()
    p(doc, "ACKNOWLEDGEMENT", bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.CENTER)
    p(
        doc,
        "I thank Dr. B. Bhaskara Rao and Ms. R. Arshiya for supervising this project and "
        "for feedback on both the machine-learning narrative and the engineering deliverables.",
    )

    doc.add_page_break()
    p(doc, "ABSTRACT", bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.CENTER)
    abstract = [
        "The AI Job Market Skill Gap Analyzer is a full-stack application that ingests resume "
        "PDFs, extracts skills, ingests job postings, and reports market fit and skill gaps "
        "with explicit score decomposition. Semantic similarity uses the pretrained "
        "SentenceTransformer model `BAAI/bge-small-en-v1.5`, loaded once in "
        "`embedding_service.py` and reused for performance.",
        "Skill extraction combines KeyBERT-style keyphrases with a curated dictionary "
        "(`data/skills_dictionary.json`) and normalization logic in `skill_service.py`, "
        "including blocklists and plausibility checks to reduce noisy “skills” that are "
        "actually sentence fragments.",
        "Job acquisition is implemented in `scraper_service.py` with a portal plugin under "
        "`portals/` (LinkedIn adapter). The reference deployment flow described in the "
        "project README builds LinkedIn search URLs for India and a last-24-hours window, "
        "parses listing pages, fetches job detail pages, and stores `Job` and `JobSkill` "
        "rows in PostgreSQL. A deduplication cache window (`SCRAPER_CACHE_DAYS`, default 7) "
        "reduces redundant network load using `external_id` hashing.",
        "Matching and gap scoring are centralized in `match_service.py`. The resume–job "
        "match score is a weighted sum: 0.50×semantic + 0.30×skill overlap + 0.20×keyword "
        "coverage − 0.20×demand penalty, with a 95% confidence interval surfaced to the "
        "UI. Demand percentages are computed from the application’s own job corpus using "
        "`job_skills` counts rather than external labor APIs.",
        "Gap analysis orchestration lives in `gap_service.py` and can run synchronously or "
        "via ARQ: `worker/tasks.py` defines `gap_analysis_task`, which the API enqueues when "
        "Redis is available; clients poll `GET /analysis/status/{task_id}` for completion.",
        "Optional coaching text is produced by `llm_service.py` through an Ollama-compatible "
        "HTTP API (`/api/generate`) when `LLM_BASE_URL` is configured; disabling it leaves "
        "numeric analysis intact. The frontend (`frontend/src/pages/Dashboard.tsx` and "
        "related components) renders fit and gap charts, job lists, and structured advice "
        "panels (`GapAdviceStructured`, `MatchAdviceStructured`).",
    ]
    for para in abstract:
        p(doc, para)

    doc.add_page_break()
    p(doc, "TABLE OF CONTENTS", bold=True, size=14, align=WD_PARAGRAPH_ALIGNMENT.CENTER)
    for line in [
        "1. Introduction",
        "2. System Context and Related Concepts",
        "3. Problem Statement, Objectives, and Scope",
        "4. Requirements and Constraints",
        "5. Architecture and Data Flow (Repository-Accurate)",
        "6. Methodology: Skill Extraction, Scraping, and Scoring",
        "7. Implementation Mapping (Modules, Routers, and Storage)",
        "8. Background Processing, Caching, and Observability",
        "9. Testing and Validation Strategy",
        "10. Results, Discussion, and Limitations",
        "11. Conclusion and Future Work",
        "12. References",
        "Appendix A. Diagrams and Evidence",
        "Appendix B. Configuration Parameters",
    ]:
        p(doc, line)

    # --- Chapter 1 ---
    chapter(doc, "CHAPTER 1  INTRODUCTION")
    for para in [
        "Campus placement preparation increasingly depends on understanding how a resume "
        "aligns with what employers currently write in job descriptions. Keyword-only tools "
        "fail when employers use synonyms, abbreviations, or role-specific phrasing. Pure "
        "semantic similarity can also mislead when two texts read similarly but differ on "
        "concrete tool requirements.",
        "The AI Job Market repository addresses this by combining three complementary "
        "signals: (1) dense-vector semantic similarity from BGE embeddings, (2) explicit "
        "skill overlap derived from extracted resume and job skills, and (3) a demand-aware "
        "penalty that increases when missing skills appear frequently across scraped postings "
        "stored in PostgreSQL.",
        "The user-facing journey documented in `README.md` begins with PDF upload, continues "
        "with “Analyze Skills Gap,” and ends with dashboard outputs: market fit percentage, "
        "gap percentage, matched and missing skills, and a ranked view of high-demand missing "
        "skills. A separate resume–job match flow opens a modal with score breakdown and "
        "optional AI advice.",
        "This thesis emphasizes engineering realism: scraping can fail, markets can be sparse, "
        "and local LLM inference can be slow on CPU-only hosts. The implemented system "
        "therefore includes fallbacks (for example, synchronous gap analysis when Redis is "
        "unavailable) and configuration knobs such as `LLM_TIMEOUT_SECONDS` documented in "
        "`backend/app/core/config.py`.",
    ]:
        p(doc, para)

    # --- Chapter 2 ---
    chapter(doc, "CHAPTER 2  SYSTEM CONTEXT AND RELATED CONCEPTS")
    for para in [
        "Sentence embeddings map text into a vector space where cosine similarity approximates "
        "semantic closeness for many short-text tasks. The repository pins the embedding "
        "model to `BAAI/bge-small-en-v1.5` for a practical tradeoff between accuracy and "
        "deployment cost on student hardware.",
        "Skill extraction in industry systems often combines dictionaries with statistical or "
        "neural keyphrase methods. This project follows that hybrid pattern: KeyBERT-style "
        "extraction proposes candidates, while dictionary-driven normalization anchors "
        "skills to canonical names and filters implausible spans.",
        "Explainable composite scoring is appropriate for academic evaluation because it lets "
        "examiners trace how a final percentage arises. The match service exposes weights "
        "as named constants (`WEIGHT_SEMANTIC`, `WEIGHT_SKILL_OVERLAP`, `WEIGHT_KEYWORD`, "
        "`WEIGHT_DEMAND_PENALTY`) so the UI can mirror the same decomposition users see "
        "during a viva demonstration.",
        "Demand as used here is not a national labor statistic. It is a normalized frequency "
        "measure computed from the jobs currently stored for the application’s scrape slice. "
        "That definition is methodologically honest and matches what the database can "
        "actually observe.",
    ]:
        p(doc, para)

    # --- Chapter 3 ---
    chapter(doc, "CHAPTER 3  PROBLEM STATEMENT, OBJECTIVES, AND SCOPE")
    for para in [
        "Problem statement: candidates need prioritized learning guidance tied to a target "
        "role, not a black-box similarity score. The system must also tolerate noisy "
        "extraction, partial job corpora, and intermittent external services.",
        "Objectives: deliver an authenticated web workflow; persist resumes and jobs; compute "
        "gap and match analytics; visualize demand-heavy missing skills; support optional local "
        "LLM summaries and advice; deploy behind nginx with systemd-managed API processes.",
        "Scope includes the implemented routers (`auth`, `resumes`, `jobs`, `analysis`, "
        "`scraper`, optional `log_viewer` for demo log tailing) and the services layer where "
        "business logic lives. Out of scope: training a new foundation model from scratch and "
        "proving hiring outcomes using labeled HR datasets.",
    ]:
        p(doc, para)

    # --- Chapter 4 ---
    chapter(doc, "CHAPTER 4  REQUIREMENTS AND CONSTRAINTS")
    for para in [
        "Functional requirements map directly to repository routes: resume upload and "
        "optional `POST /resumes/{id}/generate-summary`, job listing and detail endpoints, "
        "`POST /analysis/resume-gap`, match endpoints under `/analysis`, market trend queries, "
        "and scraper utilities for operational maintenance.",
        "Non-functional requirements include JWT-protected user isolation (`core/security.py` "
        "and `core/deps.py`), rate limiting via `slowapi` (`core/limiter.py`), and operational "
        "metrics via `prometheus-fastapi-instrumentator` at `/metrics` as noted in `CLAUDE.md`.",
        "Ethical and legal constraints matter for scraping-based projects. The thesis treats "
        "LinkedIn ingestion as an engineering integration with caching and politeness "
        "considerations, and it recommends official APIs or licensed feeds for any production "
        "deployment beyond academic demonstration.",
    ]:
        p(doc, para)

    # --- Chapter 5 ---
    chapter(doc, "CHAPTER 5  ARCHITECTURE AND DATA FLOW (REPOSITORY-ACCURATE)")
    for para in [
        "The repository’s documented architecture places the React SPA behind nginx for "
        "static hosting while proxying `/api` to Uvicorn running the FastAPI application "
        "(`app.main:create_app`). In development, Vite proxies `/api` to the backend and "
        "strips the prefix so backend routes remain rooted at paths like `/resumes` and "
        "`/analysis` rather than duplicating `/api` inside FastAPI.",
        "Core runtime services are organized under `backend/app/services/`. "
        "`resume_service.py` uses pdfplumber to extract text from PDF resumes and persists "
        "`Resume` rows plus `ResumeSkill` associations. `scraper_service.py` coordinates "
        "LinkedIn search and detail parsing and persists `Job` and `JobSkill` rows.",
        "`embedding_service.py` implements a singleton-style lazy load of the "
        "SentenceTransformer model so cold start occurs once per process rather than per "
        "request. `match_service.py` consumes embeddings and structured skill sets to compute "
        "match and gap analytics, including confidence-style messaging where implemented.",
        "`gap_service.py` orchestrates the larger gap analysis pipeline, including freshness "
        "logic and optional background execution. `llm_service.py` wraps httpx calls to "
        "Ollama’s `/api/generate` endpoint with configurable timeouts for JSON and plain "
        "advice prompts.",
        "Persistence uses PostgreSQL through SQLAlchemy async sessions (`asyncpg`). Optional "
        "Redis supports an L2 embedding cache with TTL (24 hours) and ARQ queues for "
        "`gap_analysis_task`, `prescrape_jobs` cron work, and `background_scrape_task` as "
        "defined in `worker/tasks.py` and described in `CLAUDE.md`.",
        "The frontend’s primary surface is `frontend/src/pages/Dashboard.tsx`, supported by "
        "components such as `CircularScore`, `SkillDemandChart`, `MatchScoreBreakdown`, "
        "`GapAdviceStructured`, and `MatchAdviceStructured`, which align UI visualization "
        "with backend schema outputs.",
    ]:
        p(doc, para)

    # --- Chapter 6 ---
    chapter(doc, "CHAPTER 6  METHODOLOGY: SKILL EXTRACTION, SCRAPING, AND SCORING")
    for para in [
        "Skill methodology: resumes and job descriptions are converted to text, then passed "
        "through KeyBERT-style keyphrase extraction combined with dictionary-driven "
        "normalization. Blocklists and plausibility heuristics reduce non-technical fragments. "
        "Optional embedding-based similarity against dictionary phrases can be toggled via "
        "configuration (`USE_EMBEDDING_SKILL_EXTRACTION`, `USE_SEMANTIC_SKILL_MATCHING` in "
        "settings) to catch variants not present as exact strings.",
        "Scraping methodology: LinkedIn adapter code under `portals/` constructs search URLs "
        "from skill terms and fixed location/time filters (India, last 24 hours in the "
        "reference README flow). HTML parsing extracts listing links and job detail fields. "
        "Jobs are deduplicated using a cache window keyed by hashed external identifiers, "
        "reducing repeated downloads during iterative testing.",
        "Gap methodology: after jobs and job skills exist, the system compares resume skills "
        "to the union of market skills observed in postings. Fit and gap percentages summarize "
        "coverage, while high-demand missing skills rank missing items by how often they "
        "appear across jobs in the database slice.",
        "Match methodology: for a selected job, the match pipeline combines semantic "
        "similarity between resume text and job text, explicit overlap between resume and "
        "job skill sets, keyword coverage, and a demand-weighted missing-skill penalty using "
        "the implemented constants (0.50/0.30/0.20/0.20). The service also computes a 95% "
        "confidence interval for the match score, which is surfaced in API responses for UI "
        "presentation.",
        "LLM methodology (optional): prompts are loaded from `data/prompts.json` when "
        "configured, otherwise built-in templates in `llm_service.py` are used. Structured JSON "
        "advice paths attempt to parse model output into schema-friendly objects for the "
        "dashboard, with graceful degradation if parsing fails.",
    ]:
        p(doc, para)

    # --- Chapter 7 ---
    chapter(doc, "CHAPTER 7  IMPLEMENTATION MAPPING (MODULES, ROUTERS, AND STORAGE)")
    for para in [
        "Routers are thin orchestrators: `routers/resume.py` handles uploads and summaries, "
        "`routers/jobs.py` exposes listing and match entry points, `routers/analysis.py` "
        "implements gap, match, trends, and related analytics endpoints, and `routers/scraper.py` "
        "supports operational scraping controls.",
        "`routers/auth.py` issues JWT tokens using bcrypt password hashing, enabling per-user "
        "resume isolation. This is essential for any real deployment and is part of the "
        "project’s security baseline.",
        "`routers/log_viewer.py` optionally exposes read-only log tail endpoints for demo "
        "panels when `LOG_VIEWER_ENABLED` and `LOG_VIEWER_TOKEN` are set, with routes mounted "
        "both at `/logs/*` and `/api/logs/*` in `app.main` to accommodate nginx path prefixes.",
        "Database models include `User`, `Resume`, `Job`, `Skill`, join tables for resume and "
        "job skills, and additional career/feedback tables used by advanced analytics "
        "services (as imported in `app.main`). Migrations are managed with Alembic (`uv run "
        "alembic upgrade head`).",
        "The repository also includes an Adzuna adapter (`adzuna_service.py`) as an "
        "alternative job board integration path, demonstrating that scrapers are not the "
        "only ingestion strategy the architecture can support.",
    ]:
        p(doc, para)

    # --- Chapter 8 ---
    chapter(doc, "CHAPTER 8  BACKGROUND PROCESSING, CACHING, AND OBSERVABILITY")
    for para in [
        "When Redis connects successfully, `app.main` creates an ARQ pool for background "
        "jobs; when Redis is unavailable, ARQ is disabled and gap analysis can fall back to "
        "in-process execution, preserving demo usability on minimal setups.",
        "Embedding caching reduces repeated computation for identical text hashes. The cache "
        "TTL and key format (`emb:{sha256}`) are described in `CLAUDE.md` and matter for "
        "performance when users repeatedly analyze similar resumes or jobs.",
        "Observability includes structured request logging middleware and Prometheus metrics "
        "at `/metrics`. During VM deployment, `journalctl` for the systemd unit provides "
        "additional operational evidence beyond application logs.",
        "LLM operations require careful timeout handling: httpx read timeouts are derived "
        "from `LLM_TIMEOUT_SECONDS` (default increased for CPU-only inference in recent "
        "configuration work). Ollama logs showing 60-second failures were consistent with "
        "undersized timeouts and were mitigated by raising limits and warming models before "
        "demos.",
    ]:
        p(doc, para)

    # --- Chapter 9 ---
    chapter(doc, "CHAPTER 9  TESTING AND VALIDATION STRATEGY")
    for para in [
        "Automated tests live under `backend/tests/` and are executed with `uv run pytest` as "
        "documented in `CLAUDE.md`. Tests should cover scoring edge cases, resume parsing "
        "failures, and API contracts where present.",
        "Integration validation for this thesis included end-to-end runs: upload a PDF, "
        "confirm `Resume` and `ResumeSkill` rows, trigger gap analysis, confirm job ingestion "
        "and `JobSkill` rows, and verify dashboard payloads include fit/gap and demand-ranked "
        "missing skills.",
        "Deployment validation included nginx routing for `/api`, systemd restart behavior, "
        "and verification that optional endpoints (LLM, log viewer) behave correctly when "
        "enabled or disabled via environment variables.",
    ]:
        p(doc, para)

    # --- Chapter 10 ---
    chapter(doc, "CHAPTER 10  RESULTS, DISCUSSION, AND LIMITATIONS")
    for para in [
        "Observed results: the system produces interpretable dashboards that align with "
        "intuition for common engineering resumes when the job corpus is non-empty. The "
        "explicit score breakdown supports academic explanation during defense.",
        "Limitations: demand statistics are only as representative as the scraped sample; "
        "LinkedIn HTML changes can break parsers; CPU-only LLM inference can time out on "
        "large prompts; and no labeled hiring dataset was used to validate predictive accuracy.",
        "Threats to validity include selection bias in postings, geography bias (India-focused "
        "reference flow), and temporal bias (24-hour window). These should be stated clearly "
        "in any publication or examination response.",
    ]:
        p(doc, para)

    # --- Chapter 11 ---
    chapter(doc, "CHAPTER 11  CONCLUSION AND FUTURE WORK")
    for para in [
        "Conclusion: the repository delivers a credible capstone-grade system that unifies "
        "NLP inference, structured skill analytics, scraping ingestion, and full-stack "
        "engineering. The main intellectual contribution is responsible integration with "
        "transparent scoring and honest demand semantics.",
        "Future work: expand ingestion beyond a single portal, add formal evaluation with "
        "expert-labeled relevance judgments, run ablations on weights, improve fairness "
        "reporting, and explore multilingual resumes and job descriptions.",
    ]:
        p(doc, para)

    # --- References ---
    chapter(doc, "CHAPTER 12  REFERENCES")
    refs = [
        "N. Reimers and I. Gurevych, Sentence-BERT (semantic sentence embeddings), ACL 2019.",
        "BAAI, bge-small-en-v1.5 model card and documentation (Hugging Face).",
        "M. Grootendorst, KeyBERT repository and documentation.",
        "FastAPI documentation (https://fastapi.tiangolo.com/).",
        "SQLAlchemy 2.x async documentation.",
        "PostgreSQL documentation.",
        "Redis documentation.",
        "ARQ documentation.",
        "Ollama documentation.",
        "pdfplumber documentation.",
        "scikit-learn cosine similarity documentation.",
        "Project repository README.md and CLAUDE.md (implementation facts cited in this thesis).",
    ]
    for r in refs:
        p(doc, r)

    # --- Appendix A ---
    doc.add_page_break()
    p(doc, "APPENDIX A  DIAGRAMS AND EVIDENCE", bold=True, size=14)
    p(
        doc,
        "Insert screenshots of the Dashboard upload flow, gap results, match modal, and "
        "production logs. Include the architecture diagram used in internal documentation.",
    )
    if IMG.exists():
        doc.add_picture(str(IMG), width=Inches(6.2))
        p(
            doc,
            "Fig. A.1  Job scraper ecosystem flow (client → nginx → FastAPI → PostgreSQL / "
            "Redis / ARQ / Ollama → external job boards).",
            align=WD_PARAGRAPH_ALIGNMENT.CENTER,
        )

    # --- Appendix B ---
    doc.add_page_break()
    p(doc, "APPENDIX B  KEY CONFIGURATION PARAMETERS", bold=True, size=14)
    cfg_lines = [
        "DATABASE_URL — async PostgreSQL DSN for SQLAlchemy.",
        "EMBEDDING_MODEL — defaults to BAAI/bge-small-en-v1.5.",
        "SIMILARITY_THRESHOLD / SKILL_SIMILARITY_THRESHOLD / SEMANTIC_MATCH_THRESHOLD — "
        "similarity gates used in extraction and matching pipelines.",
        "SCRAPER_CACHE_DAYS — deduplication window for scraped jobs (default 7).",
        "REDIS_URL — enables Redis cache and ARQ when reachable; empty disables.",
        "LLM_BASE_URL / LLM_MODEL / LLM_TIMEOUT_SECONDS — Ollama integration and HTTP timeouts.",
        "JWT_SECRET_KEY / JWT_EXPIRE_MINUTES — authentication token settings.",
        "LOG_VIEWER_ENABLED / LOG_VIEWER_TOKEN / LOG_FILE_PATH — optional demo log viewer.",
    ]
    for line in cfg_lines:
        p(doc, line)

    # --- Additional project-specific narrative (unique paragraphs; not template loops) ---
    doc.add_page_break()
    p(doc, "APPENDIX C  IMPLEMENTATION DEEP DIVE (REPOSITORY-SPECIFIC)", bold=True, size=14)
    deep = [
        "The analysis router exposes both a standard JSON gap endpoint and a streaming "
        "variant. `POST /analysis/resume-gap-stream` emits Server-Sent Events that carry "
        "progress messages and a final structured result, which is important for long "
        "runs where scraping and embedding work would otherwise leave the user uncertain "
        "about whether the server is still working.",
        "`GapAnalysisService` validates that a resume exists, ensures skills are extracted "
        "through `ResumeService.ensure_resume_skills`, and then coordinates scraping with "
        "`ScraperService.scrape_quick`, which intentionally caps immediate work (`max_quick`) "
        "while optionally handing remaining URLs to `background_scrape_task` when an ARQ "
        "pool exists. This split is a pragmatic engineering response to HTTP latency limits.",
        "The scraper path records scrape timestamps and uses cache keys so repeated analyses "
        "for the same skill context do not necessarily repeat full network fetches. When "
        "enqueueing fails, the code logs a warning and continues, reflecting a best-effort "
        "background strategy rather than a hard failure of the primary user request.",
        "Match scoring is not only a single scalar: the API returns structured fields used by "
        "the React modal to render `MatchScoreBreakdown`, separating semantic, overlap, "
        "keyword, and demand components. Presenting components separately is central to the "
        "thesis claim of explainability and is directly visible to examiners during UI demo.",
        "Confidence and uncertainty messaging appears in related services (for example, "
        "confidence labels derived from corpus size and similarity spread). Even when not "
        "shown as a formal ML calibration curve, these heuristics communicate honesty about "
        "data sufficiency, which is academically preferable to pretending certainty.",
        "The skill layer includes demand aggregation routines used by both gap and trends "
        "features. Trend endpoints (implemented in the analysis router and skill service) "
        "support weekly views that contextualize volatility and growth for skills tied to a "
        "resume, which extends the project beyond a static snapshot into a lightweight "
        "time-series narrative suitable for placement discussions.",
        "Career-oriented extensions in the repository (career path, trajectory, role fit) "
        "demonstrate that the architecture is extensible beyond the core gap story. For a "
        "thesis, these modules can be framed as future-facing modules that reuse the same "
        "embedding and skill machinery rather than as unrelated features.",
        "Security is handled with standard patterns: password hashing, JWT issuance, and a "
        "FastAPI dependency for current user context. This matters because resumes are "
        "sensitive; the thesis should explicitly connect authentication to privacy risk "
        "mitigation, even if the capstone deployment is not a full compliance audit.",
        "Rate limiting is applied to expensive endpoints such as gap analysis to reduce "
        "abuse risk during public demos. This is a small but real production concern and "
        "shows that the implementation considers operational abuse, not only functional correctness.",
        "The embedding cache reduces repeated downloads of model weights indirectly by "
        "reducing repeated heavy CPU work; combined with lazy model loading, it stabilizes "
        "latency after warm-up. Students writing the thesis should report warm-up effects "
        "honestly because they are typical for transformer inference on CPU.",
        "The optional log viewer is a demonstration feature: it exposes read-only tailing of "
        "rotated log files when enabled. The thesis can use this as evidence of execution "
        "during defense, while also noting that it must be disabled after public exposure "
        "because it is token-gated but still sensitive operationally.",
        "Frontend engineering uses Axios with a configurable base URL (`VITE_API_URL` defaulting "
        "to `/api`) so the same client can run behind Vite dev proxy or nginx production "
        "routing. This configuration detail is frequently overlooked in write-ups but is "
        "exactly the kind of integration fact examiners ask about when discussing deployment.",
        "Database migrations matter for reproducibility: the thesis should mention Alembic "
        "because schema drift is a common reason student demos fail on a fresh machine. "
        "Including the exact commands from `CLAUDE.md` makes the document operationally useful.",
        "Testing philosophy should include scraping fragility: HTML parsers are inherently "
        "brittle. The thesis narrative should treat scraper maintenance as ongoing engineering, "
        "not a one-time task, and propose monitoring for layout changes.",
        "The demand penalty term is only as meaningful as deduplication and skill normalization "
        "quality. If two different strings map to different skills incorrectly, demand counts "
        "split. The repository mitigates this with normalization utilities and clustering "
        "logic in match-related services; these deserve explicit mention because they are "
        "part of the scientific story, not incidental code.",
        "Finally, the thesis should close the loop between claims and artifacts: every major "
        "claim—explainability, demand grounding, optional LLM—should point to a concrete file "
        "or endpoint. That discipline is what makes the document read as engineering research "
        "rather than generic AI hype.",
    ]
    for para in deep:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX D  FRONTEND AND UX MAPPING TO BACKEND CONTRACTS", bold=True, size=14)
    fe = [
        "The React router configuration in `frontend/src/App.tsx` exposes a public landing "
        "route at `/` and nests the dashboard under `/app`, wrapped by `Layout`. This routing "
        "choice separates marketing-style landing content from authenticated dashboard tooling.",
        "The dashboard is the primary user workspace: it coordinates resume selection, upload, "
        "gap analysis triggers, job browsing, and match modal interactions. Each interaction "
        "maps to REST calls implemented in FastAPI routers and typed client helpers in "
        "`frontend/src/api/client.ts` (Axios instance with `/api` base URL).",
        "Visualization components such as `SkillDemandChart` and `CircularScore` translate "
        "numeric payloads into charts and radial progress indicators. These components matter "
        "for thesis evaluation because they demonstrate that explainability is not only text: "
        "it is also visual communication of demand and fit.",
        "Tailwind CSS provides consistent spacing and typography across the dashboard. While "
        "styling is not the scientific core, it affects usability during demonstration and "
        "signals professional frontend engineering quality.",
        "Dark/light theme support is implemented through a React context under `frontend/src/"
        "contexts/`. Theme toggles are minor features but useful to mention because they show "
        "attention to accessibility and long demo sessions.",
        "The match modal workflow depends on stable schema types returned by the backend. "
        "When the backend adds fields (for example confidence labels or breakdown subscores), "
        "the TypeScript client should be updated to prevent silent UI drift. This is standard "
        "full-stack maintenance and should appear in a thesis limitations or maintenance section.",
        "Error handling in the UI should surface `parseApiError` behavior from the Axios "
        "client, which normalizes FastAPI error payloads into user-readable strings. This is "
        "particularly important for long-running gap analysis where timeouts may occur.",
        "For production builds, `npm run build` emits static assets consumed by nginx. The "
        "thesis should explicitly connect the build artifact path to nginx root configuration "
        "because examiners often ask how the SPA is served in deployment.",
        "End-to-end demo scripts should include: clearing browser cache, confirming API health "
        "via `/health`, verifying Redis status fields, and optionally warming the embedding "
        "model with a trivial encode to avoid first-request latency during scoring.",
    ]
    for para in fe:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX E  DATA MODEL AND ANALYTICS EXTENSIONS", bold=True, size=14)
    dm = [
        "The PostgreSQL schema stores normalized skills and join tables linking resumes and "
        "jobs to skills. This design supports aggregate demand queries because counting "
        "mentions reduces to SQL joins rather than ad-hoc text scanning at request time.",
        "Additional analytics tables and services (feedback, career progress, global insights) "
        "extend the core gap narrative. In a thesis, these can be described as optional modules "
        "that reuse the same embeddings and skill infrastructure, demonstrating extensibility.",
        "Simulation endpoints (where present) allow hypothetical skill additions to estimate "
        "score movement. This is academically interesting because it connects the UI to "
        "counterfactual reasoning (“what if I learn X?”) without claiming causal hiring impact.",
        "Role fit suggestions and trajectory predictions (if enabled in deployment) rely on "
        "corpus statistics derived from stored jobs. Their accuracy depends on corpus breadth; "
        "therefore they should be framed as exploratory analytics rather than certified career counseling.",
        "Database migrations and seed routines (such as curated corpus seeding described in "
        "`app.main` lifespan hooks) help keep demos functional when scraping is blocked. "
        "Mentioning seed behavior is important because it explains why a fresh install can "
        "still show non-empty markets.",
    ]
    for para in dm:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX F  STEP-BY-STEP EXECUTION TRACE (FOR VIVA / EXAMINER Q&A)", bold=True, size=14)
    trace = [
        "Step A — Environment preparation: create PostgreSQL database `ai_resume_analyzer`, "
        "install backend dependencies with `uv sync`, apply migrations with `uv run alembic "
        "upgrade head`, and configure `.env` from `.env.example`. This sequence is explicitly "
        "documented because schema mismatch is a frequent root cause of failed demos.",
        "Step B — Start API: `uv run uvicorn app.main:app --reload` exposes OpenAPI at `/docs`, "
        "which is useful for verifying that routers mounted correctly after refactors such as "
        "dual-mounting the log viewer under `/logs` and `/api/logs`.",
        "Step C — Optional Redis and worker: `uv run arq worker.WorkerSettings` enables "
        "`gap_analysis_task` and scraping follow-ups. The `/health` endpoint reports whether "
        "Redis connected and whether ARQ pool creation succeeded at startup.",
        "Step D — Frontend dev: `npm run dev` serves the SPA on port 5173 with `/api` proxied "
        "to the backend. Students should confirm that axios calls succeed and that CORS "
        "origins include the dev server origin configured in backend settings.",
        "Step E — Resume upload: `POST /resumes/upload` stores raw text and extracted skills. "
        "If `LLM_BASE_URL` is set, the system may generate `ai_summary` text stored on the "
        "resume row; if not, the numeric pipeline still proceeds.",
        "Step F — Gap analysis: `POST /analysis/resume-gap` runs `GapAnalysisService.analyze`. "
        "During scraping, `scrape_quick` returns immediate results and may leave remaining "
        "URLs for `background_scrape_task` when ARQ is available, which is why the UI may show "
        "partial job counts that grow over time.",
        "Step G — SSE alternative: `POST /analysis/resume-gap-stream` is useful when panelists "
        "ask for proof of progress; streaming events show incremental status rather than a "
        "silent spinner while scraping proceeds.",
        "Step H — Match modal: `GET /analysis/match` consumes embeddings and structured skills "
        "to return breakdown fields rendered by `MatchScoreBreakdown`. Examiners should be "
        "invited to compare breakdown numbers against the implemented constants in "
        "`match_service.py`.",
        "Step I — Market trends: trend endpoints aggregate weekly posting behavior from "
        "timestamped job rows. This is a distinct feature from gap fit and should be explained "
        "as time-series analytics rather than as part of the core scoring formula.",
        "Step J — Production VM: nginx serves `frontend/dist` and proxies `/api` to Uvicorn. "
        "systemd manages the API process. Logs are collected via journald and optionally via "
        "file appenders when `LOG_FILE_PATH` is configured for the log viewer feature.",
        "Step K — Evidence bundle: screenshots should include Swagger `/docs`, a successful "
        "gap response JSON excerpt (redacted), the dashboard charts, and `journalctl` lines "
        "showing request timing middleware output.",
        "Step L — Failure drills: intentionally stop Redis and show that gap analysis still "
        "returns, demonstrating graceful degradation paths implemented in application startup "
        "and service constructors.",
        "Step M — LLM drill: show Ollama `api/tags`, then run gap analysis with LLM enabled; "
        "if timeouts occur, show configuration change to `LLM_TIMEOUT_SECONDS` and restart. "
        "This ties thesis claims to reproducible operational troubleshooting.",
        "Step N — Data ethics drill: explain caching windows, rate limits, and why the project "
        "does not claim compliance with third-party terms of service. Academic honesty here "
        "protects the student during cross-examination.",
        "Step O — Reproducibility package: include exact Python version, `uv.lock` presence, "
        "embedding model download behavior on first run, and disk space requirements after "
        "model download, because these are practical constraints examiners appreciate.",
    ]
    for para in trace:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX G  RISK REGISTER AND MITIGATIONS (PROJECT-SPECIFIC)", bold=True, size=14)
    risks = [
        "Risk: LinkedIn HTML changes break parsers. Mitigation: isolate parsing in portal "
        "adapters, add defensive parsing tests, and document fallback to corpus seeding when "
        "available.",
        "Risk: Sparse job corpus yields unstable demand percentages. Mitigation: show "
        "confidence messaging, widen time window only if policy allows, and disclose sample size.",
        "Risk: Embedding model download fails on slow networks. Mitigation: pre-download on "
        "deployment machine and verify model cache directory permissions.",
        "Risk: JWT secret left at default in production. Mitigation: enforce strong random "
        "secrets and warn on startup when insecure defaults are detected (as implemented in "
        "lifespan warnings).",
        "Risk: Public log viewer exposure. Mitigation: disable after demo, rotate token, and "
        "restrict nginx access if possible.",
        "Risk: CPU-only LLM latency causes HTTP timeouts. Mitigation: increase read timeout, "
        "use smaller models, warm models, or disable LLM for quantitative-only demos.",
        "Risk: Database migration drift between team members. Mitigation: commit migrations and "
        "require `alembic upgrade head` in deployment checklist.",
        "Risk: Misconfigured `/api` prefix causes 404 routes. Mitigation: dual-mount log "
        "routes and document nginx rewrite rules explicitly in deployment notes.",
        "Risk: Rate limiting blocks legitimate rapid testing. Mitigation: document limiter "
        "configuration for dev environments and separate prod tuning.",
        "Risk: Sensitive resume content in logs. Mitigation: avoid logging raw resume text at "
        "INFO level; rely on structured request logs with IDs only.",
    ]
    for para in risks:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX H  USER-JOURNEY AND API CONTRACT DETAILS (FROM README)", bold=True, size=14)
    hj = [
        "The landing route (`/`) introduces the product and routes users toward the dashboard. "
        "This separation is standard for SPAs and keeps authentication-heavy UI away from "
        "public marketing content.",
        "The dashboard lists scraped jobs and intentionally filters sign-in-like pages so "
        "demo users do not click into LinkedIn authentication traps. That behavior is a "
        "small but important UX safeguard when scraping public search pages.",
        "The match workflow uses the same resume dropdown as gap analysis, which reduces "
        "cognitive load: users do not re-upload or re-select different identifiers for two "
        "related tasks.",
        "The README’s summary table maps user actions to backend routes: upload uses "
        "`POST /resumes/upload`, summary refresh uses `POST /resumes/{id}/generate-summary`, "
        "and gap analysis uses `POST /analysis/resume-gap` (plus the streaming alternative). "
        "This mapping should appear in the thesis appendix because it is concrete evidence "
        "of traceability between UI and API.",
        "Market trend analytics use `GET /analysis/market-trends` and compute weekly growth, "
        "volatility, and emerging skills over an eight-week window based on `Job.created_at`. "
        "This is distinct from instantaneous gap fit and should be described as longitudinal "
        "market visualization rather than as part of the instantaneous composite score.",
        "Backend dependencies listed in `backend/pyproject.toml` include FastAPI, SQLAlchemy "
        "async stack, sentence-transformers, scikit-learn, torch, pdfplumber, httpx, and "
        "BeautifulSoup. The thesis should mention these explicitly because they justify the "
        "engineering feasibility and resource footprint claims.",
        "The repository’s backend folder tree places schemas under `app/schemas/` and models "
        "under `app/models/`, enforcing separation between persistence models and API "
        "response contracts. That separation reduces accidental leakage of internal fields.",
        "Docker support exists for the backend image build, which is relevant for reproducible "
        "deployment even when the primary demo uses a VM with systemd instead of containers.",
        "Tailwind configuration uses `darkMode: 'class'`, which pairs naturally with the React "
        "theme context and demonstrates consistent design engineering rather than ad-hoc CSS.",
        "The README emphasizes that demand percentages are computed only from the database, "
        "which is a defensible engineering choice: it avoids third-party labor API costs while "
        "making the statistical population explicit.",
        "The README also states LinkedIn location/time defaults used in the reference flow "
        "(India, last 24 hours). The thesis must treat these defaults as configuration "
        "constraints that affect external validity rather than universal truth.",
        "Optional Adzuna integration (`adzuna_service.py`) is part of the architecture story "
        "because it shows the scraper layer is not the only ingestion strategy; alternative "
        "adapters can be registered through the portal registry pattern.",
        "The `data/prompts.json` file is part of the LLM story: it allows prompt tuning without "
        "recompiling code, which is useful for iterative capstone refinement while keeping "
        "version control of prompt changes.",
        "The `skills_dictionary.json` file anchors skill normalization. The thesis should "
        "explain that dictionary coverage determines recall for known technologies, while "
        "embedding-assisted modes help with variants when enabled.",
        "The `/metrics` endpoint exposes Prometheus instrumentation, which is valuable for "
        "demonstrating production awareness even if examiners do not request live Grafana panels.",
        "The `/health` endpoint reports Redis and ARQ connectivity, which is a practical "
        "readiness check for deployment scripts and for distinguishing “API up” from "
        "“background pipeline up.”",
        "The README’s architecture ASCII diagram can be cited as the canonical high-level "
        "view, while the ecosystem diagram image in Appendix A provides a complementary "
        "visual suitable for printed thesis submission.",
        "When describing match scoring, include both the point estimate and the 95% confidence "
        "interval behavior documented in the README, because intervals communicate uncertainty "
        "without requiring a full Bayesian treatment in an undergraduate thesis.",
        "The README’s user journey section is useful for writing “evaluation by scenario”: "
        "each scenario becomes a reproducible script the examiner can follow during defense.",
        "Finally, the thesis should connect the README’s stated behavior to actual tests: "
        "where pytest covers logic, cite test files; where behavior is manual, document the "
        "checklist used during your own validation sessions.",
    ]
    for para in hj:
        p(doc, para)

    doc.add_page_break()
    p(doc, "APPENDIX I  FORMULA AND INTERPRETATION GUIDE FOR EXAMINERS", bold=True, size=14)
    fg = [
        "Let S denote semantic similarity scaled for presentation, O denote skill overlap, "
        "K denote keyword coverage, and D denote a demand-weighted missing-skill penalty term. "
        "The implemented composite uses weights 0.50, 0.30, 0.20, and 0.20 respectively, with "
        "the demand term subtracted. Examiners should verify these constants in "
        "`match_service.py` during code review.",
        "Interpretation rule: if D is large, the candidate is missing multiple skills that "
        "appear frequently in the stored job postings, so the final score should drop even "
        "when S is moderately high. This is intentional: employers often treat missing core "
        "stack items as disqualifying even when narrative similarity is strong.",
        "Interpretation rule: if O is high but K is low, the candidate may share skills but "
        "miss exact phrasing used in ATS keyword filters. The composite still retains a lexical "
        "channel to reflect that practical hiring reality.",
        "Confidence intervals on match scores should be described as uncertainty estimates "
        "derived from the implementation’s statistical helper rather than as externally "
        "calibrated hiring probabilities unless additional labeled data is collected.",
    ]
    for para in fg:
        p(doc, para)

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
