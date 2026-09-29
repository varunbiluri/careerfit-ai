# CareerFit AI — Project Summary

**Capstone project:** Full-stack application for resume–job skill gap analysis using transformer embeddings, demand-weighted scoring, and **Ollama** with **Llama 2** for the local LLM (resume summary, skill verification, gap/match advice).

---

## 1. Abstract

Automated resume–job matching and skill-gap analysis increasingly rely on semantic embeddings and keyword overlap. Existing systems seldom incorporate labor-market demand when scoring a candidate’s fit or quantifying skill gaps, which can lead to recommendations that underweight high-demand missing skills. This project implements a **Demand-Weighted Semantic Skill Gap** approach that combines:

- **Transformer-based semantic similarity** (BGE embeddings) between resume and job text  
- **Skill overlap** and **keyword coverage** from extracted skills  
- **Demand-weighted penalty** for missing skills that appear frequently in job postings  

The composite score is formulated as **Score = αS + βO + γK − δD** (e.g. 0.5S + 0.3O + 0.2K − 0.2D), where *S* is semantic similarity, *O* is skill overlap, *K* is keyword coverage, and *D* is the demand-weighted gap term. The system extracts skills from resumes using AI (KeyBERT + structured parsing) and optional LLM verification, scrapes job boards by those skills, and produces fit %, gap %, matched/missing skills, and high-demand missing skills to prioritize learning. We use **Ollama** with **Llama 2** as the local LLM: it powers AI resume summary on upload, skill verification (cleaning KeyBERT output into real skill names), gap advice (Prioritize / Highlight / Next step from your skills + matched + missing), and match advice (Fit / Highlight / Improve for a specific job). The framework is practical for deployment in resume analyzers and career-gap tools without requiring large labeled datasets or custom model training.

---

## 2. Literature Survey

### 2.1 Resume–Job Matching and Semantic Similarity

Automated resume–job matching has moved from keyword and TF-IDF methods to **transformer-based semantic similarity**. BERT and its variants encode resume and job text into dense vectors; **cosine similarity** in this embedding space is used as a match signal, capturing meaning beyond exact keyword overlap.

**Key work:** Adnan et al. [1] use BERT for end-to-end resume parsing and candidate ranking against job descriptions. **Sentence-BERT (SBERT)** [2] trains siamese BERT networks to produce fixed-size sentence embeddings, reducing the cost of comparing many resume–job pairs (e.g. from hours to seconds) while preserving accuracy. Comparative studies (e.g. [3]) show that BERT and Sentence-BERT outperform traditional keyword and TF-IDF baselines for resume screening. More recent systems such as **Resume2Vec** [4] and **ConFit v2** [5] use intelligent resume embeddings and hard-negative mining to improve precision and recall; **LLM-based matching** (e.g. GPT-4) has been compared to human ratings, with findings that LLM scores correlate only moderately with human judgment and that prompt engineering (e.g. chain-of-thought) can improve quality [6].

A **limitation** of semantic-only scoring is that it does not explicitly model skill overlap, keyword coverage, or labor-market demand; hence hybrid approaches that combine embeddings with skill-based and demand-aware terms are needed for interpretable, market-aligned gap analysis.

| Ref | Topic | Link |
|-----|--------|------|
| [1] | End-to-end resume parsing and candidate matching with BERT | https://arxiv.org/abs/1910.03089 |
| [2] | Sentence-BERT: sentence embeddings using Siamese BERT | https://aclanthology.org/D19-1410/ |
| [3] | Comparing BERT and Sentence-BERT for automated resume screening | https://ijai.iaescore.com/index.php/IJAI/article/view/25807 |
| [4] | Resume2Vec: intelligent resume embeddings for ATS | https://www.mdpi.com/2079-9292/14/4/794 |
| [5] | ConFit v2: resume–job matching with hypothetical embeddings and hard-negative mining | https://aclanthology.org/2025.findings-acl.661/ |
| [6] | Human and LLM-based resume matching: observational study | https://aclanthology.org/2025.findings-naacl.270/ |

---

### 2.2 Skill Extraction and Ontologies

Skill extraction from resumes and job descriptions is done via **named entity recognition (NER)**, **dictionary- or ontology-based matching**, and **embedding-based keyphrase extraction**.

**NER:** CRF-based and neural NER models identify skill entities (and related types such as qualification, experience, occupation) in job text; benchmark corpora with tens of thousands of annotated entities report F1 on the order of 0.59–0.61 for skill spans [7], [8]. **NNOSE** (Nearest Neighbor Occupational Skill Extraction) [9] uses retrieval-augmented language models for occupational skill extraction, improving span-F1 for infrequent skills without extra fine-tuning.

**Ontologies:** Extracted skills are often mapped to **ESCO** (European Skills, Competences, Qualifications and Occupations) and **O*NET** (US occupational taxonomy) for normalization and cross-job comparison; the ESCO–O*NET crosswalk supports alignment between these frameworks [10], [11].

**Keyphrase / embedding-based:** **KeyBERT** [12] uses BERT document and n-gram embeddings with cosine similarity to extract keyphrases that best represent a document, without a fixed skill dictionary—suitable for adaptive extraction of evolving and variant skill names. This project uses KeyBERT plus structured parsing (e.g. “Skills” sections, comma-separated lists) and optional LLM verification to obtain resume and job skills.

| Ref | Topic | Link |
|-----|--------|------|
| [7] | Benchmark corpus for entity recognition in job descriptions (Skill, Qualification, Experience, etc.) | https://aclanthology.org/2022.lrec-1.128/ |
| [8] | OJD DAPS skills extraction (NER, model cards) | https://nestauk.github.io/ojd_daps_skills/model_card/ |
| [9] | NNOSE: nearest neighbor occupational skill extraction | https://arxiv.org/abs/2401.17092 / https://aclanthology.org/2024.eacl-long.35/ |
| [10] | ESCO taxonomy | https://esco.ec.europa.eu/en |
| [11] | O*NET Resource Center; ESCO–O*NET crosswalk | https://onetcenter.org/ ; https://esco.ec.europa.eu/en/about-esco/data-science-and-esco/crosswalk-between-esco-and-onet |
| [12] | KeyBERT: BERT-based keyphrase extraction | https://github.com/MaartenGr/KeyBERT ; https://maartengr.github.io/KeyBERT/ |

---

### 2.3 Composite Scoring and Explainability

Applicant Tracking Systems (ATS) and research prototypes often combine **multiple signals**—semantic similarity, skill overlap, keyword coverage—into a single match score via **linear or weighted combinations**. Such composite scores improve over semantic-only or keyword-only baselines and support **explainability**: showing which skills matched, which are missing, and how much each component (e.g. semantic, overlap, keyword) contributes.

Few works, however, integrate **labor-market demand** (prevalence of skills across job postings) into the score. Demand-weighted terms can penalize missing *high-demand* skills more than rare ones, aligning recommendations with what employers actually ask for. This project’s **DW-SSGI** formulation (Score = αS + βO + γK − δD) embeds demand *D* directly into the composite score and into gap reporting (high-demand missing skills first), without requiring external labor surveys—demand is computed from the same scraped job corpus used for matching.

---

### 2.4 Labor Market and Demand-Aware Methods

Labor-market analytics and **skill demand indices** are used in economics and HR to measure which skills are most requested in job postings and where **skills mismatches** (gaps between worker skills and employer demand) occur.

**LinkedIn’s Skills Mismatch** methodology [13] compares skills in job postings with skills on worker profiles to identify shortages and surpluses; such mismatches are linked to hiring friction and productivity. Regional and sectoral reports (e.g. [14], [15]) show that demand varies by geography and occupation, and that soft skills (e.g. communication) and technical skills (e.g. AI/ML, cloud) dominate posting language. **In-demand skill dashboards** (e.g. Randstad [16]) cluster skills (AI & automation, data science, cloud, etc.) for workforce planning.

This project’s contribution is to embed **demand** into a single resume–job and **skill-gap** score: demand φ(s) = (number of jobs mentioning skill *s*) / (total jobs) is computed from the application’s own job corpus; the demand-weighted gap term *D* and high-demand missing skill lists use this φ(s) so that candidates see which missing skills matter most in the current market snapshot.

| Ref | Topic | Link |
|-----|--------|------|
| [13] | LinkedIn Economic Graph: skills mismatch (technical note) | https://economicgraph.linkedin.com/content/dam/me/economicgraph/en-us/PDF/technicalnote-skills-mismatch.pdf |
| [14] | Occupational mobility / skills in demand (e.g. Cleveland Fed) | https://www.clevelandfed.org/publications/cd-reports/20250425-occupational-mobility-explorer-skills-most-in-demand |
| [15] | Indeed Hiring Lab: jobs and hiring trends | https://www.hiringlab.org/ |
| [16] | Randstad: in-demand skills dashboard | https://randstadenterprise.com/in-demand-skills/dashboard |

---

## 3. Advantages and Disadvantages

### 3.1 Advantages

| Advantage | Description |
|-----------|-------------|
| **Demand-aware scoring** | Penalizes missing skills by how often they appear in the job market, so high-demand gaps are prioritized. |
| **Semantic matching** | BGE embeddings capture meaning (e.g. “REST API” ≈ “Backend API”); not limited to exact keyword match. |
| **Adaptive skill extraction** | KeyBERT + structured parsing + optional LLM verification detects skills without a fixed dictionary; handles new and variant skill names. |
| **Explainable output** | Fit %, gap %, matched/missing lists, high-demand missing skills, and score breakdown (S, O, K, D) with 95% CI. |
| **Ollama + Llama 2 (local LLM)** | We use Ollama with Llama 2 for AI resume summary, skill verification, gap advice, and match advice; all run locally (default `http://localhost:11434`), no data sent to external APIs. |
| **Single corpus for demand** | Demand % is computed from scraped jobs in the DB; no external labor-market API required. |
| **Full pipeline in one app** | Upload resume → auto gap analysis → scrape by skills → see fit/gap and AI advice; resume–job match with score and advice. |
| **Market trends** | Time-based skill analytics (weekly growth %, volatility, top emerging skills) filtered by resume when selected. |
| **No custom training** | Uses off-the-shelf BGE and KeyBERT; deployable in days. |

### 3.2 Disadvantages

| Disadvantage | Description |
|--------------|-------------|
| **Scraping dependency** | Job market data depends on LinkedIn (and optional portals) scraping; rate limits, HTML changes, or geo restrictions can affect availability. |
| **Fixed geography/time** | Search is currently fixed (e.g. India, last 24h); not configurable per user in the default flow. |
| **No ground-truth labels** | Match and gap scores are not validated against human relevance labels; evaluation would require labeled data. |
| **Ollama + Llama 2 optional** | Best experience (summary, advice, skill verification) needs Ollama running locally with Llama 2 (or another model); without it, only structured gap and match scores are shown. |
| **Skill noise** | Extraction can yield non-skills (e.g. sentence fragments); mitigated by plausible-skill checks and LLM verification but not eliminated. |
| **Single market snapshot** | Demand and trends reflect only the jobs in the DB (e.g. one scrape); not a live global labor-market index. |
| **Resource use** | BGE and KeyBERT load in memory; first request can be slower; GPU optional but helpful for embedding throughput. |

---

## 4. Flow / Pipeline

### High-level pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  USER: Upload PDF resume                                                          │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  BACKEND: Extract text (pdfplumber) → Extract skills (KeyBERT + structured       │
│           parsing) → Optional Ollama verify_skills → Store Resume + ResumeSkill  │
│           Optional: Ollama resume summary → Store ai_summary                      │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  USER: (Auto or manual) Analyze Skills Gap                                        │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  BACKEND: get_skills_for_scrape(resume_id) → resume skills + top market skills   │
│           → ScraperService.scrape_by_skills(skill_terms, location=India, 24h)   │
│           → LinkedIn (and portals): build_search_url(skills) → fetch & parse     │
│           → Store Job + JobSkill (skills from job descriptions via KeyBERT)     │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  BACKEND: MatchService.compute_resume_gap(resume_id)                              │
│           Market = all distinct skills from JobSkill (scraped jobs)               │
│           Matched = resume skills that exactly or semantically match market      │
│           Missing = market skills not matched (filtered: blocklist, plausible)   │
│           Fit % = |matched| / |market| × 100   Gap % = 100 − Fit %                │
│           High-demand missing = missing skills ranked by demand %                 │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  BACKEND (optional Ollama): gap_advice(your_skills, matched, missing,            │
│           high_demand_missing, resume_excerpt, market_job_descriptions)          │
│           → Prioritize / Highlight / Next step (text or JSON)                  │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  FRONTEND: Show fit %, gap %, Your skills / Matched / Missing,                    │
│            high-demand missing (chart + cards), matching explanation, AI advice   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Resume–job match flow

```
User selects resume + job → GET /analysis/match?job_id=&resume_id=
  → BGE embeddings(resume, job) → S = cosine similarity
  → Skill overlap O, keyword coverage K
  → Demand penalty D = avg demand % of missing skills
  → Score = 0.5S + 0.3O + 0.2K − 0.2D (95% CI)
  → Optional Ollama match_advice(resume, job) → Fit / Highlight / Improve
  → Frontend: modal with score breakdown, matched/missing, AI advice
```

### Market trends flow

```
GET /analysis/market-trends?resume_id=&weeks=8
  → skill_trends(): weekly job counts per skill (Job.created_at)
  → weekly_growth_pct, volatility_index, top_emerging (positive growth)
  → Filter to resume’s skills when resume_id provided
  → Frontend: summary cards (weekly growth, volatility), top emerging list
```

---

## 5. Tech Stack

### Backend

| Component | Technology |
|-----------|------------|
| **Runtime** | Python 3.11 |
| **API** | FastAPI, Uvicorn |
| **Database** | PostgreSQL, SQLAlchemy (async), asyncpg |
| **Validation / config** | Pydantic, pydantic-settings |
| **Embeddings** | sentence-transformers, BAAI/bge-small-en-v1.5 (BGE) |
| **ML / similarity** | scikit-learn (cosine similarity, etc.), PyTorch |
| **Skill extraction** | KeyBERT (keyphrase extraction from text) |
| **PDF** | pdfplumber (text extraction from resume PDFs) |
| **HTTP / scraping** | httpx, BeautifulSoup4 |
| **Local LLM** | **Ollama** with **Llama 2** — backend talks to Ollama’s API (default `http://localhost:11434`). We use Llama 2 (set `LLM_MODEL=llama2`); other models e.g. llama3.2 are supported. Used for: resume summary, verify_skills, gap_advice, match_advice. Optional: set `LLM_BASE_URL` empty to disable. |
| **Package / env** | uv, python-dotenv, python-multipart |

### Frontend

| Component | Technology |
|-----------|------------|
| **Framework** | React 18 |
| **Build** | Vite 5 |
| **Language** | TypeScript |
| **Styling** | Tailwind CSS, PostCSS, Autoprefixer |
| **HTTP** | Axios |
| **Routing** | react-router-dom |
| **Charts** | Recharts |

### Infrastructure / DevOps

| Component | Technology |
|-----------|------------|
| **Backend container** | Docker (Dockerfile in backend) |
| **Deploy (docs)** | Render (backend), Vercel (frontend) — see docs/DEPLOYMENT_CAPSTONE.md |

---

## 6. Reference Papers and Links

### Resume–job matching and semantic similarity

| # | Topic | Link | Note |
|---|--------|------|------|
| 1 | End-to-end resume parsing and candidate matching with BERT | https://arxiv.org/abs/1910.03089 | BERT for resume–job matching |
| 2 | Sentence-BERT: sentence embeddings with Siamese BERT | https://aclanthology.org/D19-1410/ | Semantic similarity for sentences |
| 3 | Comparing BERT and Sentence-BERT for resume screening | https://ijai.iaescore.com/index.php/IJAI/article/view/25807 | Automated resume screening |

### Embedding models

| # | Topic | Link | Note |
|---|--------|------|------|
| 4 | BGE (BAAI General Embedding) — bge-small-en-v1.5 | https://huggingface.co/BAAI/bge-small-en-v1.5 | Model used in this project |
| 5 | BGE v1 & v1.5 documentation | https://bge-model.com/bge/bge_v1_v1.5.html | Architecture and usage |

### Skill extraction and ontologies

| # | Topic | Link | Note |
|---|--------|------|------|
| 6 | KeyBERT — BERT-based keyphrase extraction | https://github.com/MaartenGr/KeyBERT | Keyphrase extraction used for skills |
| 7 | KeyBERT documentation | https://maartengr.github.io/KeyBERT/ | Usage and options |
| 8 | ESCO (European Skills, Competences, Qualifications and Occupations) | https://esco.ec.europa.eu/en | Skill/occupation taxonomy |
| 9 | O*NET Resource Center (occupations and skills) | https://onetcenter.org/ | US occupational taxonomy |
| 10 | Crosswalk between ESCO and O*NET | https://esco.ec.europa.eu/en/about-esco/data-science-and-esco/crosswalk-between-esco-and-onet | Linking skill frameworks |

### Demand-weighted scoring and labor market

| # | Topic | Link | Note |
|---|--------|------|------|
| 11 | Project paper draft (Demand-Weighted Semantic Skill Gap) | `docs/Demand_Weighted_Resume_Skill_Gap_Paper_Draft.md` | DW-SSGI formulation, baselines, experiments |
| 12 | Research execution plan (5–7 days) | `docs/Research_Paper_5-7_Day_Plan.md` | Baseline vs proposed, metrics, ablation |

### Ollama (local LLM) and prompts

| # | Topic | Link | Note |
|---|--------|------|------|
| 13 | **Ollama** — local LLM runtime we use | https://ollama.com | Install Ollama, then run `ollama run llama2`; backend uses `LLM_BASE_URL=http://localhost:11434` and `LLM_MODEL=llama2` (configurable). |
| 14 | **Llama 2** (Meta) — model used with Ollama | https://ai.meta.com/llama/ | Open-weight LLM; we use it via Ollama for resume summary, skill verification, gap advice, and match advice. |
| 15 | Local LLM and prompts (project docs) | `docs/LOCAL_LLM_AND_PROMPTS.md` | Setup, prompt keys: resume_summary, verify_skills, gap_advice, match_advice |

---

## 7. Suggested citation (for academic use)

If you use this project or the demand-weighted scoring idea in research, you can adapt the following:

> We use a demand-weighted semantic skill gap formulation (Score = αS + βO + γK − δD) with BGE embeddings [BAAI/bge-small-en-v1.5], skill extraction via KeyBERT, and a local LLM (Ollama with Llama 2) for resume summary, skill verification, and gap/match advice, following ideas in transformer-based resume–job matching [1,2] and demand-aware gap prioritization.

Replace [1,2] with the specific papers (e.g. arxiv.org/abs/1910.03089, Sentence-BERT) as required by your venue.

---

*This summary is generated from the project README, paper draft, and codebase. For run instructions and environment variables, see the main [README.md](../README.md).*
