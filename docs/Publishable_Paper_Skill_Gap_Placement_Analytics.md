# CareerFit AI

**B. Sai Vignesh**  
Department of Computer Science and Engineering (Data Science), Rajeev Gandhi Memorial College of Engineering and Technology (Autonomous), Nandyal, India  
**Supervisor:** Dr. B. Bhaskara Rao  
**Co-Supervisor:** Ms. R. Arshiya

---

## Abstract

Students preparing for placements usually have access to many job descriptions, but they lack a practical way to decide what to learn next. Basic keyword matching fails on paraphrased requirements, while single-score semantic matching often hides important missing skills. This paper presents a deployable full-stack system, **CareerFit AI**, that processes resume PDFs, extracts and normalizes skills, builds a market slice from recent postings, and generates two kinds of outputs: (i) market gap summaries and (ii) resume-job pairwise match scores with transparent component breakdowns. The scoring function combines semantic similarity, structured skill overlap, keyword evidence, and a demand-based penalty for missing high-frequency skills. The system is implemented using FastAPI, PostgreSQL, React, and optional Redis/ARQ/Ollama modules. We define demand conservatively as frequency within the active corpus slice, not as a universal labor-market indicator. The contribution is a reproducible and explainable systems integration approach suitable for academic placement analytics.

**Keywords:** skill gap analysis, resume-job matching, sentence embeddings, explainable scoring, demand weighting, full-stack analytics.

---

## I. Introduction

Placement preparation is often handled manually: students compare their resumes against job descriptions and try to infer learning priorities from scattered requirements. This process is time-consuming and inconsistent, especially when equivalent skills are expressed using different vocabulary. For example, a resume may mention "REST APIs" while a job posting states "backend service development." Keyword-only filters frequently miss such alignment.

The goal of this work is to provide a practical, explainable system that helps students answer three questions:

1. How well does my current skill profile fit the target job market slice?  
2. Which skills am I missing?  
3. Which missing skills appear frequently enough in the current postings to prioritize first?

To answer these questions, we built **CareerFit AI**, a production-style capstone with authenticated resume upload, skill extraction, job scraping and storage, demand estimation over the ingested corpus, and a dashboard for gap and match analysis.

---

## II. System Design Overview

The platform follows a modular client-server architecture.

- **Frontend:** React + TypeScript + Vite dashboard for upload, analysis, and visualization.  
- **Backend:** FastAPI with async SQLAlchemy services and PostgreSQL persistence.  
- **Optional infrastructure:** Redis for caching and ARQ workers for background tasks.  
- **Optional advisory layer:** Ollama for local LLM-based explanation text.

### A. Core Data Objects

The main entities are user, resume, resume skills, job, and job skills. This relational model allows straightforward aggregation queries for demand and trend summaries.

### B. Pipeline

1. Resume PDF upload and text extraction.  
2. AI-first skill extraction and normalization (with optional dictionary merge).  
3. Job ingestion through scraper modules and deduplication.  
4. Gap and match score computation.  
5. Presentation of interpretable outputs in the dashboard.

---

## III. Skill Processing and Demand Estimation

The current repository defaults to AI/keyphrase-driven extraction (`use_ai_skill_extraction=True`) with optional dictionary extraction (`use_dictionary_skill_extraction`) for blended operation. Resume and job texts are normalized so that variants such as "js", "javascript", and related aliases align consistently. This step significantly improves overlap computation quality compared to raw token matching.

Let \( \phi(s) \) denote demand for skill \( s \), defined as normalized frequency in the active market slice. In this repository, defaults are `live_market_only=True`, `persist_scraped_jobs=False`, and `persist_resumes=False`, so demand is often computed from in-memory live registries unless persistence is explicitly enabled. This definition is intentionally local and reproducible. We do not claim that \( \phi(s) \) represents national or global labor demand.

Gap analysis reports:

- matched skills,  
- missing skills,  
- high-demand missing skills ranked by \( \phi(s) \),  
- aggregate fit and gap summaries.

---

## IV. Match Scoring Model

For resume-job pairwise analysis, the implementation combines four channels:

- \(S\): semantic similarity from sentence embeddings,  
- \(O\): structured skill overlap,  
- \(K\): keyword overlap signal,  
- \(D\): demand-weighted penalty for missing important skills.

The composite score is:

\[
\text{Score} = 0.50S + 0.30O + 0.20K - 0.20D
\]

The system also computes a 95% confidence interval for reported match values where available, providing uncertainty-aware interpretation instead of a single overconfident number.

---

## V. Implementation Details

The backend service layer is organized around dedicated modules for embeddings, skills, matching, gap orchestration, scraping, and optional LLM support. This separation improves maintainability and allows individual components to be switched or tuned without rewriting the full application.

### A. Technology Stack

- **Modeling:** SentenceTransformers using `BAAI/bge-small-en-v1.5`  
- **API:** FastAPI  
- **Database:** PostgreSQL  
- **Queue/cache (optional):** Redis + ARQ  
- **Frontend:** React + TypeScript + Tailwind  
- **Deployment:** nginx + Uvicorn (VM setup)

### B. Reliability Features

- JWT-based user isolation  
- Password hashing with bcrypt  
- Rate limiting for expensive endpoints  
- `/health` and `/metrics` endpoints for operational visibility  
- Graceful fallback behavior when optional services are disabled

### C. Code-Accurate Runtime Defaults

- Semantic skill matching is enabled by default (`use_semantic_skill_matching=True`).  
- Live market-only mode is enabled by default (`live_market_only=True`).  
- Redis is disabled by default (`redis_url=""`), so background queue/cache remain optional.  
- Job and resume persistence are disabled by default and can be turned on per deployment.  
- Startup may seed a curated corpus when DB job volume is below configured thresholds.

---

## VI. Observations from Deployment and Use

The system performs well for educational deployment scenarios where users expect actionable guidance rather than strict hiring predictions. The breakdown view was particularly useful during demonstrations because reviewers could see how each score component contributed.

Practical observations include:

- Semantic similarity alone is insufficient for prioritization.  
- Demand-aware penalties improve skill prioritization quality.  
- Caching and background tasks reduce repeated latency under demo workloads.  
- Optional LLM advice improves readability but should remain secondary to deterministic outputs.

---

## VII. Limitations and Validity Threats

This study deliberately avoids exaggerated claims. Current limitations are:

1. **Sample dependence:** Demand reflects only ingested postings.  
2. **Scraping fragility:** Source HTML changes can affect extraction quality.  
3. **No hiring-outcome labels:** The system is not validated against real recruitment outcomes.  
4. **LLM variability:** Advice quality and latency vary by local model and hardware.

These limitations define clear future evaluation priorities rather than weakening the engineering contribution.

---

## VIII. Conclusion and Future Work

This paper presented a practical and explainable resume-job skill alignment system for placement preparation. The primary contribution is not a new neural architecture, but a reproducible integration of semantic matching, structured skill analysis, demand-aware prioritization, and deployable software engineering.

Future work includes:

- labeled ranking evaluation (Precision@K / Recall@K),  
- ablation studies on demand weighting,  
- multi-source job ingestion with bias analysis,  
- stronger fairness and compliance reporting,  
- multilingual resume and job support.

---

## References

[1] N. Reimers and I. Gurevych, “Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks,” *EMNLP*, 2019.  
[2] BAAI, “bge-small-en-v1.5,” Hugging Face model card.  
[3] M. Grootendorst, “KeyBERT: Minimal keyword extraction with BERT,” project documentation.  
[4] FastAPI Documentation, SQLAlchemy Async Documentation, PostgreSQL Documentation.  
[5] Redis Documentation and ARQ Task Queue Documentation.  
[6] Ollama Documentation.  
[7] pdfplumber Documentation.

---

## Submission Notes

- Add institutional email and final author block formatting as required by the target venue.  
- Convert this manuscript to IEEE two-column format (`IEEEtran`) for conference submission.  
- If quantitative experiments are completed, replace narrative observations with result tables and figures.
