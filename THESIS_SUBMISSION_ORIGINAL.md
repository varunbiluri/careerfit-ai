# Undergraduate Thesis (Original Draft)

**Title:** AI Job Market Skill Gap Analyzer — Explainable, Demand-Aware Resume–Market Alignment

**Author:** B. Sai Vignesh  
**Department:** Computer Science and Engineering (Data Science)  
**Institution:** Rajeev Gandhi Memorial College of Engineering & Technology (Autonomous), Nandyal  
**Academic Year:** 2025–2026  
**Supervisors:** Dr. B. Bhaskara Rao; Ms. R. Arshiya  

---

## Candidate Declaration

I declare that the narrative, system description, and conclusions in this document reflect my own understanding of the work I carried out. Where external methods or software libraries are mentioned, they are cited in the references section. I have not copied long passages from internet sources or prior student reports.

**Signature:** ____________________ **Date:** ____________________

---

## Abstract

Job seekers often receive feedback that is either too shallow (keyword hits) or too opaque (a single similarity score). This thesis describes a full-stack system that estimates how well a resume aligns with a target role while explaining *why* the alignment is strong or weak. The approach combines three ideas that are simple individually but powerful together: (1) semantic text comparison using pretrained sentence embeddings, (2) explicit skill lists extracted from resumes and job descriptions, and (3) a demand-sensitive treatment of missing skills, where skills that appear frequently in recent postings receive higher priority than rare mentions.

The system is implemented as a web application with a React dashboard and a FastAPI backend backed by PostgreSQL. Optional local large-language-model assistance is supported for readable coaching text, but the quantitative gap and match logic does not depend on an external cloud API. The main contribution is engineering and applied NLP integration: turning heterogeneous resume and job text into an interpretable upskilling plan grounded in a scraped job sample.

**Keywords:** skill gap analysis, semantic similarity, keyphrase extraction, demand weighting, FastAPI, PostgreSQL, local LLM.

---

## Chapter 1 — Introduction

### 1.1 Motivation

Campus hiring and internship preparation increasingly depend on online job boards. Candidates need guidance that goes beyond “add keywords.” They need to know which missing capabilities matter in the current posting window for their chosen role family. This project addresses that need with a transparent pipeline from PDF upload to prioritized learning suggestions.

### 1.2 Problem Statement

Traditional keyword screening fails when employers use synonyms, abbreviations, or role-specific phrasing. Pure embedding similarity can miss hard skill requirements because text similarity does not always imply capability coverage. This work therefore combines semantic similarity with explicit skill overlap and a demand-aware penalty so that missing high-frequency skills cannot be ignored.

### 1.3 Objectives

1. Build an end-to-end system for resume ingestion, skill extraction, job ingestion, and gap reporting.  
2. Provide explainable scoring with visible components rather than a black-box percentage.  
3. Rank missing skills using frequency signals derived from the project’s own job corpus.  
4. Deploy the system on commodity hardware with optional local LLM assistance.

### 1.4 Scope and Non-Goals

**In scope:** PDF resume parsing, skill extraction, job scraping adapters, gap and match endpoints, dashboard visualization, VM deployment.  
**Out of scope:** training a new foundation model from scratch; proving hiring outcomes with labeled HR data; nationwide labor statistics integration.

---

## Chapter 2 — Related Work and Concepts (Concise)

Semantic matching for recruitment is widely discussed using transformer sentence embeddings. Skill extraction appears in NER literature and in keyphrase extraction practice. Explainable composite scoring is common in HR-tech prototypes. This thesis does not claim a new theorem; it integrates known signals into a deployable product with explicit weighting and operational constraints suitable for a capstone deployment.

---

## Chapter 3 — Requirements

Functional requirements include authenticated resume upload, gap analysis, job match breakdown, and optional AI text. Non-functional requirements include reasonable latency on CPU-only hosts, graceful degradation when Redis or LLM services are unavailable, and clear logging for demonstration and maintenance.

---

## Chapter 4 — System Architecture

The browser talks to nginx, which serves the built frontend and proxies API calls to Uvicorn. The API layer orchestrates services for embeddings, skills, matching, gap computation, scraping, and optional LLM calls. PostgreSQL stores users, resumes, jobs, and extracted skills. Redis supports caching and ARQ background tasks when enabled.

---

## Chapter 5 — Methodology

### 5.1 Data Acquisition

Resumes arrive as PDFs. Jobs are collected through configured scrapers and cached to avoid redundant network load. Skills are extracted using keyphrase-oriented NLP plus normalization rules to reduce noise.

### 5.2 Scoring Design (Explainable)

The composite score is expressed as a weighted combination of semantic similarity (S), skill overlap (O), keyword coverage (K), and a demand-weighted missing-skill term (D). Weights are kept explicit in code so the UI can explain the final number. Demand percentages are interpreted strictly as *relative frequencies within the stored job sample*, not as official labor-market statistics.

### 5.3 Outputs

The user receives fit and gap summaries, matched and missing skill sets, and a ranked list of high-demand missing skills. Optional LLM text summarizes the same facts in coaching language.

---

## Chapter 6 — Implementation Notes

The backend uses async database access, structured configuration, and modular services to keep routers thin. The frontend uses TypeScript for safer UI development. Deployment uses systemd for the API process and nginx for static hosting and reverse proxying.

---

## Chapter 7 — Evaluation and Discussion

Because labeled hiring outcomes were not collected, evaluation is framed as functional validation, qualitative sanity checks on extracted skills, and stability under realistic demo loads. The main limitation is dependence on scraper coverage and the representativeness of the posting sample.

---

## Chapter 8 — Conclusion

The project delivers a practical, explainable resume–market alignment tool suitable for capstone demonstration and further research. Future work includes curated evaluation datasets, sensitivity analysis on weights, broader job sources, and fairness reporting across demographic proxies where data permits.

---

## References (Short List — Expand in IEEE/APA Format Required by Your Department)

1. Sentence-BERT (sentence embeddings for semantic similarity).  
2. BGE embedding model documentation (pretrained model card).  
3. KeyBERT (keyphrase extraction).  
4. FastAPI documentation.  
5. PostgreSQL documentation.  
6. Redis documentation.  
7. Ollama documentation (local LLM runtime).

---

## Appendix A — Figures and Evidence (You Must Attach)

- Architecture diagram exported from your design tool.  
- Screenshots of upload, gap dashboard, match modal, and VM logs.  
- Plagiarism certificate from your college tool (if required).
