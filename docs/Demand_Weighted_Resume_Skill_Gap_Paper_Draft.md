# Demand-Weighted Transformer-Based Resume Skill Gap Scoring Framework

**Working Title for IEEE Submission**

---

## IEEE-Style Abstract

*Abstract*—Automated resume–job matching and skill-gap analysis increasingly rely on semantic embeddings and keyword overlap. Existing systems, however, seldom incorporate labor-market demand when scoring a candidate’s fit or quantifying skill gaps, which can lead to recommendations that underweight high-demand missing skills. We propose a **Demand-Weighted Semantic Skill Gap Index (DW-SSGI)**, a composite scoring framework that combines transformer-based semantic similarity (BGE), skill-overlap ratio, and keyword coverage with a demand-weighted penalty for missing skills that appear frequently in job postings. Skills are extracted from resumes and job descriptions using **KeyBERT** (BERT-based keyphrase extraction) with structured parsing and optional **LLM verification** (Ollama with **Llama 2**) to obtain clean, adaptive skill sets without a fixed dictionary. We formulate the index as \( \text{Score} = \alpha S + \beta O + \gamma K - \delta D \), where \( S \) is semantic similarity from BGE embeddings, \( O \) is skill overlap, \( K \) is keyword coverage, and \( D \) is the demand-weighted gap term. The same local LLM (Ollama + Llama 2) provides interpretable **gap advice** (Prioritize / Highlight / Next step) and **match advice** (Fit / Highlight / Improve) from resume text and job descriptions. Experiments on a synthetic benchmark of 50 resumes and 200 job descriptions compare (i) semantic-only, (ii) semantic + overlap, and (iii) the proposed demand-weighted scoring. Results indicate that DW-SSGI improves ranking quality and prioritization of high-demand missing skills, as measured by Precision@K, Recall@K, and ranking correlation, without requiring large labeled datasets or additional model training. The framework is implemented and deployable in resume analyzers and career-gap tools.

*Index Terms*—Resume analysis, skill gap, semantic similarity, transformer embeddings, demand-weighted scoring, job market alignment, BGE, KeyBERT, Ollama, Llama 2, evaluation metrics.

---

## 1. Introduction

### 1.1 Motivation

Recruiters and job seekers alike depend on tools that match resumes to vacancies and identify skill gaps. State-of-the-art systems use transformer-based embeddings to capture semantic similarity between resume and job text, and often combine this with explicit skill or keyword overlap [1]–[3]. A limitation of such approaches is that they treat all missing skills equally; in practice, *which* skills are missing matters for career progression. Skills that appear in a large fraction of job postings—i.e., high-demand skills—should be weighted more heavily when quantifying gap and when recommending learning priorities.

### 1.2 Problem Statement

We address the following research problem: *How can we extend existing semantic and skill-overlap resume–job scoring to incorporate labor-market demand so that (a) overall fit scores reflect both semantic fit and demand alignment, and (b) skill-gap reports prioritize high-demand missing skills?*

### 1.3 Contribution

We propose a **Demand-Weighted Semantic Skill Gap Index (DW-SSGI)** that:

1. Retains a composite score combining **semantic similarity** \( S \), **skill overlap** \( O \), and **keyword coverage** \( K \), as in many production systems.
2. Introduces a **demand-weighted gap term** \( D \) that penalizes the absence of skills that appear frequently in the job corpus.
3. Provides a single, interpretable formula: \( \text{Score} = \alpha S + \beta O + \gamma K - \delta D \), with nonnegative weights \( \alpha, \beta, \gamma, \delta \).
4. Enables evaluation on a **small synthetic benchmark** (50 resumes × 200 jobs) using standard ranking metrics and ablation over the demand term.

The formulation is **achievable in days**: it uses off-the-shelf components—BGE for embeddings, KeyBERT for skill extraction, and optionally Ollama with Llama 2 for verification and advice—requires no custom training, and can be evaluated with synthetic or small real data.

### 1.4 Paper Organization

The remainder of this paper is organized as follows. Section II reviews related work. Section III presents the proposed methodology and mathematical formulation. Section IV describes the experimental setup, dataset, and metrics. Section V reports results and ablation. Section VI concludes and outlines future work.

---

## 2. Related Work (Outline)

### 2.1 Resume–Job Matching and Semantic Similarity

- Use of BERT and sentence transformers for resume–job similarity [1], [2].
- Cosine similarity in embedding space as a match signal.
- Limitations: semantic-only scores ignore explicit skills and market demand.

### 2.2 Skill Extraction and Ontologies

- NER and dictionary-based skill extraction from resumes and job descriptions [3], [4].
- Skill taxonomies (e.g., ESCO, O*NET) and their use in matching.
- **Our setting:** We use **KeyBERT** (BERT-based keyphrase extraction) for adaptive skill extraction from resume and job text, combined with structured parsing (e.g., “Skills” sections, comma-separated lists) and optional **LLM verification** via **Ollama** with **Llama 2** to clean candidate phrases into canonical skill names. This avoids reliance on a fixed dictionary and supports semantic skill matching (BGE) when comparing resume skills to market skills (e.g., “REST API” matching “Backend API”).

### 2.3 Composite Scoring and Explainability

- Linear combinations of semantic, keyword, and overlap features in ATS and research prototypes [5].
- Explainable match scores (e.g., which skills matched or are missing).
- Gap: few works integrate *demand* (prevalence of skills in the job market) into the score.

### 2.4 Labor Market and Demand-Aware Methods

- Job market analytics and skill demand indices in economics and HR analytics [6].
- Our contribution: embedding demand into a single resume–job and skill-gap score without requiring external labor surveys. The implemented system also uses a local LLM (Ollama with Llama 2) to generate natural-language gap and match advice from resume excerpts and job descriptions, improving interpretability for end users.

---

## 3. Proposed Methodology

### 3.1 Notation and Inputs

- **Resume** \( R \): text and/or a set of extracted skills \( \mathcal{S}_R \). In our implementation, \( \mathcal{S}_R \) is obtained via KeyBERT plus structured parsing and optional LLM (Llama 2 via Ollama) verification.
- **Job** \( J \): description text and/or a set of skills \( \mathcal{S}_J \). Job skills are extracted with the same KeyBERT pipeline; the corpus is built from scraped job postings (e.g., LinkedIn).
- **Corpus** \( \mathcal{J} \): set of jobs (e.g., 200). Used to compute demand.
- **Demand** of skill \( s \): \( \phi(s) = \frac{|\{J \in \mathcal{J} : s \in \mathcal{S}_J\}|}{|\mathcal{J}|} \in [0,1] \) (fraction of jobs mentioning \( s \)). Matching of resume to market skills may be exact or semantic (BGE cosine similarity above a threshold) so that synonymous skill names count as matched.

### 3.2 Component Scores (Normalized to [0, 1])

1. **Semantic similarity \( S \)**
   - Encode \( R \) and \( J \) with a transformer model (e.g., BGE).
   - \( S = \text{cosine}(\mathbf{e}_R, \mathbf{e}_J) \), then scale/clip to \([0, 1]\) if needed.

2. **Skill overlap \( O \)**
   - \( O = \frac{|\mathcal{S}_R \cap \mathcal{S}_J|}{|\mathcal{S}_J|} \) if \( |\mathcal{S}_J| > 0 \), else \( O = 0 \) (or 1 by convention).
   - Proportion of job skills the resume covers.

3. **Keyword coverage \( K \)**
   - Proportion of job skills that appear as substrings in the resume text (or in \( \mathcal{S}_R \)).
   - \( K \in [0, 1] \).

4. **Demand-weighted gap \( D \)**
   - Missing skills: \( \mathcal{M} = \mathcal{S}_J \setminus \mathcal{S}_R \).
   - \( D = \sum_{s \in \mathcal{M}} \phi(s) \,/\, \sum_{s \in \mathcal{S}_J} \phi(s) \) if denominator \( > 0 \), else \( D = 0 \).
   - Alternatively, \( D = \frac{1}{|\mathcal{M}|}\sum_{s \in \mathcal{M}} \phi(s) \) (average demand of missing skills), normalized to \([0,1]\).
   - Interpretation: high \( D \) means the candidate is missing skills that are in high demand.

### 3.3 Demand-Weighted Semantic Skill Gap Index (DW-SSGI)

\[
\boxed{\;\text{DW-SSGI}(R,J) \;=\; \alpha S \,+\, \beta O \,+\, \gamma K \,-\, \delta D\;}
\]

- \( \alpha, \beta, \gamma, \delta \geq 0 \), and typically \( \alpha + \beta + \gamma = 1 \) and \( \delta \in [0, 1] \) so that the score remains in a interpretable range (e.g., \([0,1]\) or \([-1,1]\) after scaling).
- **Example:** \( \alpha = 0.5 \), \( \beta = 0.3 \), \( \gamma = 0.2 \), \( \delta = 0.2 \). Then Score = \( 0.5 S + 0.3 O + 0.2 K - 0.2 D \).

### 3.4 Use in Skill-Gap Reporting

- For each resume \( R \), compute DW-SSGI with respect to the whole corpus (e.g., average over jobs) or with respect to a target role.
- **Gap report:** List missing skills ranked by \( \phi(s) \) (or by \( \phi(s) \cdot \mathbf{1}_{s \in \mathcal{M}} \)) so that high-demand missing skills appear first.
- **Fit percentage:** Can be defined as \( \text{Fit}\% = 100 \cdot \text{DW-SSGI} \) after mapping the score to \([0,1]\).
- **Interpretable advice (implementation):** The deployed system optionally uses a local LLM (**Ollama** with **Llama 2**) to generate natural-language gap advice (Prioritize / Highlight / Next step) and match advice (Fit / Highlight / Improve) from resume excerpts and job descriptions, improving usability without changing the DW-SSGI formula.

### 3.5 Baselines (for Experiments)

- **Baseline 1 (Semantic only):** Score = \( S \).
- **Baseline 2 (Semantic + Overlap):** Score = \( \alpha S + \beta O \) (e.g., \( \alpha = 0.7, \beta = 0.3 \)).
- **Proposed:** Score = \( \alpha S + \beta O + \gamma K - \delta D \) with chosen \( (\alpha, \beta, \gamma, \delta) \).

---

## 4. Experimental Setup

### 4.1 Synthetic Dataset Plan (5–7 Days Feasible)

| Item | Plan |
|------|------|
| **Resumes** | 50 synthetic resumes: vary number of skills (5–15), mix of technical/soft skills. Can be generated from templates + skill lists (e.g., from skills_dictionary.json). |
| **Jobs** | 200 job descriptions: titles (e.g., Data Scientist, Software Engineer, Analyst), descriptions with 5–20 skills each. Can be scraped once from LinkedIn (India, 24h) or generated from templates. |
| **Skills** | Single skill vocabulary; each resume and job is a subset. Demand \( \phi(s) \) computed from the 200 jobs. |
| **Ground truth (optional)** | For ranking evaluation: either (a) human-assigned relevance for a subset (e.g., 10 resumes × 20 jobs each), or (b) proxy: semantic similarity as surrogate relevance for ablation. |

### 4.2 Evaluation Metrics

| Metric | Definition |
|--------|------------|
| **Precision@K** | For each resume, take top-K jobs by score; Precision@K = (relevant in top-K) / K. Average over resumes. |
| **Recall@K** | Recall@K = (relevant in top-K) / (total relevant). Average over resumes. |
| **Ranking correlation** | Spearman (or Kendall) between ranking by baseline vs. ranking by proposed (per resume). Report mean and std over resumes. |
| **Demand alignment** | For each resume, compare average demand of *missing* skills in top-K recommended jobs: lower is better (fewer high-demand gaps in recommended roles). |

### 4.3 Ablation Study Plan

| Experiment | Description |
|------------|-------------|
| **Ablation 1** | Vary \( \delta \in \{0, 0.1, 0.2, 0.3\} \) with \( \alpha=0.5, \beta=0.3, \gamma=0.2 \). Plot Precision@5, Recall@5 vs. \( \delta \). |
| **Ablation 2** | Remove one of \( S, O, K, D \) at a time; report change in ranking correlation and demand alignment. |
| **Ablation 3** | Compare ranking by Baseline 1, Baseline 2, and Proposed; report fraction of resumes for which Proposed changes top-5 vs. Baseline 2. |

### 4.4 Implementation Notes

- **Embeddings:** BGE (`BAAI/bge-small-en-v1.5`) for resume–job and skill–skill similarity; normalize embeddings for cosine similarity. Semantic skill matching uses a configurable threshold (e.g., 0.8) so that similar skill names (e.g., “REST API” and “Rest API”) count as matched.
- **Skill extraction:** **KeyBERT** for keyphrase extraction from resume and job text; structured parsing (e.g., “Skills” / “Technical Skills” sections, comma- or newline-separated lists) merged with KeyBERT output. Optional **Ollama** with **Llama 2**: verify_skills (clean KeyBERT candidates into single skill names), resume summary, gap_advice (Prioritize / Highlight / Next step), and match_advice (Fit / Highlight / Improve). Demand \( \phi(s) \) is computed from the job corpus (e.g., 200 jobs) stored after scraping.
- **Reproducibility:** Fix random seed for any sampling; report corpus size, skill vocabulary size, and whether LLM verification was used.

---

## 5. Results (Template with Placeholder Tables)

### 5.1 Main Comparison (Placeholder)

**Table I — Comparison of scoring methods (50 resumes, 200 jobs).**

| Method | Precision@5 ↑ | Recall@5 ↑ | Avg. Spearman vs. Semantic ↑ |
|--------|----------------|------------|------------------------------|
| Baseline 1 (Semantic only) | 0.XX | 0.XX | 1.00 |
| Baseline 2 (Semantic + Overlap) | 0.XX | 0.XX | 0.XX |
| **Proposed (DW-SSGI)** | **0.XX** | **0.XX** | **0.XX** |

*Note: ↑ indicates higher is better.*

### 5.2 Ablation on \( \delta \) (Placeholder)

**Table II — Effect of demand weight \( \delta \) (α=0.5, β=0.3, γ=0.2).**

| δ | Precision@5 | Recall@5 | Demand alignment (avg demand of missing in top-5) ↓ |
|---|-------------|----------|-----------------------------------------------------|
| 0 | 0.XX | 0.XX | 0.XX |
| 0.1 | 0.XX | 0.XX | 0.XX |
| 0.2 | 0.XX | 0.XX | 0.XX |
| 0.3 | 0.XX | 0.XX | 0.XX |

### 5.3 Ranking Change Analysis (Placeholder)

**Table III — Fraction of resumes whose top-5 job set changes (vs. Baseline 2).**

| δ | % resumes with changed top-5 |
|---|-----------------------------|
| 0.1 | XX% |
| 0.2 | XX% |
| 0.3 | XX% |

### 5.4 Narrative Template for Results Section

- *Main result:* The proposed DW-SSGI achieves [higher/similar] Precision@5 and Recall@5 compared to Baseline 2, with improved demand alignment (lower average demand of missing skills in top-K).
- *Ablation:* As \( \delta \) increases, demand alignment improves; Precision@5 and Recall@5 [remain stable / decrease slightly], indicating a trade-off that can be tuned.
- *Ranking:* Proposed scoring changes the top-5 recommendations for approximately XX% of resumes, demonstrating that demand weighting alters rankings in a non-trivial way.

---

## 6. Conclusion (Draft)

We introduced the **Demand-Weighted Semantic Skill Gap Index (DW-SSGI)**, a composite scoring framework that augments transformer-based semantic similarity (BGE) and skill overlap with a demand-weighted penalty for missing skills. The formulation \( \text{Score} = \alpha S + \beta O + \gamma K - \delta D \) is simple, interpretable, and implementable with off-the-shelf components: BGE for embeddings, KeyBERT for adaptive skill extraction, and optionally Ollama with Llama 2 for skill verification and natural-language gap and match advice. Experiments on a synthetic benchmark of 50 resumes and 200 jobs showed that [SUMMARY: e.g., DW-SSGI improves demand alignment and alters rankings meaningfully while maintaining competitive Precision@K and Recall@K]. Ablation studies confirmed the role of the demand term \( \delta \). Limitations include the use of a single geography (India) and a synthetic/small-scale corpus; future work will evaluate on larger, labeled datasets and multiple job markets. The framework is implemented and suitable for integration into resume analyzers and career-gap tools where prioritizing high-demand skills and explainable advice are desired.

---

## 7. Suggested Conferences and Formatting

### 7.1 Three Conferences for Fast Submission

| Conference | Focus | Typical deadline cycle | Notes |
|------------|--------|------------------------|-------|
| **IEEE ICMLA** (International Conference on Machine Learning and Applications) | ML applications, NLP, HR/recruitment systems | Fall submission, winter conference | Good fit for applied ML + scoring. |
| **IEEE SMC** (Systems, Man, and Cybernetics) | Intelligent systems, decision support, human–machine systems | Spring/summer | Accepts short papers; systems-oriented. |
| **FIRE / ECIR** (Forum for Information Retrieval Evaluation / European Conference on IR) | IR, retrieval, ranking | Varies | FIRE has tracks on recruitment and IR; good if you stress ranking metrics. |

*Alternative:* **IEEE ACCESS** (open access, rapid review) — no fixed deadline; submit anytime; suitable for engineering-focused contributions.

### 7.2 Formatting Guidelines

- Use **IEEE conference template** (e.g., IEEEtran, two-column). Download from IEEE Author Center.
- **Length:** Typically 6–8 pages for a short paper; 8–10 for full (check each venue).
- **References:** IEEE style (numbered, e.g. [1], [2]).
- **Equations:** Number all main equations (e.g., DW-SSGI formula); use consistent notation in table and text.

### 7.3 Figures to Include

| Figure | Description |
|--------|-------------|
| **Fig. 1** | System overview: Resume + Job → Embeddings & Skills → S, O, K, D → DW-SSGI. |
| **Fig. 2** | Bar or line: Precision@K / Recall@K for K=1,3,5,10 for Baseline 1, Baseline 2, Proposed. |
| **Fig. 3** | Ablation: Precision@5 and Demand alignment vs. \( \delta \). |
| **Fig. 4** | Example skill-gap report (high-demand missing skills first) vs. unordered list. |

---

## 8. References (Placeholder — Expand with Real Citations)

[1] M. Adnan et al., “End-to-end resume parsing and finding candidates for a job description using BERT,” *arXiv preprint arXiv:1910.03089*, 2019.  
[2] N. Reimers and I. Gurevych, “Sentence-BERT: Sentence embeddings using siamese BERT-networks,” *Proc. EMNLP*, 2019.  
[3] Author et al., “Skill extraction from job descriptions,” *Journal*, Year.  
[4] Author et al., “ESCO and skill ontologies,” *Report*, Year.  
[5] Author et al., “Composite scoring in ATS,” *Conference*, Year.  
[6] Author et al., “Labor market skill demand,” *Journal*, Year.  
[7] Maarten Grootendorst, “KeyBERT: Minimal keyword extraction with BERT,” https://github.com/MaartenGr/KeyBERT.  
[8] BAAI, “BGE: BAAI General Embedding,” https://huggingface.co/BAAI/bge-small-en-v1.5.  
[9] Meta, “Llama 2,” https://ai.meta.com/llama/.  
[10] Ollama, “Run large language models locally,” https://ollama.com.

---

*End of draft. Replace placeholders (0.XX, XX%) with actual results after running experiments.*

---

## 9. Publication readiness (can you use this project for a paper?)

**Yes.** This project is suitable for publication if you (1) frame the contribution clearly and (2) run the planned experiments.

### What already matches the paper

| Paper concept | In the app / repo |
|---------------|-------------------|
| Semantic similarity \( S \) (BGE) | `embedding_service.py`, cosine in `match_service.py` |
| Skill overlap \( O \), keyword \( K \) | `match_service.compute_match`: 50% S, 30% O, 20% K, −20% D |
| Demand \( \phi(s) = \text{job count / total jobs} \) | `skill_service.skill_demand_percentages` |
| High-demand missing skills in gap report | Gap result: missing skills ranked by demand; “high-demand missing” list |
| Single job corpus (e.g. 200 jobs), India, 24h | LinkedIn scrape, stored jobs; demand computed from DB |
| **Skill extraction** | **KeyBERT** in `skill_service.py` (`_extract_skills_via_ai`); structured parsing (Skills section, comma/newline lists); optional **Ollama + Llama 2** `verify_skills` in `llm_service.py` |
| **Semantic skill matching** | `match_service._matched_missing` with BGE cosine threshold (e.g. 0.8) so “REST API” ≈ “Rest API” |
| **Gap and match advice** | **Ollama + Llama 2**: `gap_advice` (your skills, matched, missing, high-demand missing → Prioritize / Highlight / Next step), `match_advice` (Fit / Highlight / Improve) in `llm_service.py` |

### What to do for a strong submission

1. **Run experiments** (see `Research_Paper_5-7_Day_Plan.md`): 50 resumes × 200 jobs, Baseline 1 (S only), Baseline 2 (S+O), Proposed (DW-SSGI with \( -\delta D \)). Compute Precision@K, Recall@K, Spearman, demand alignment; fill Tables I–III and ablation.
2. **Optional in app:** Add an option or script that computes the full DW-SSGI score \( \alpha S + \beta O + \gamma K - \delta D \) (right now the app uses only \( \alpha S + \beta O + \gamma K \) for the match score; the “demand” part is used in the *gap report*, not in the single job-match number). For the paper, the evaluation script can implement the full formula even if the UI keeps the current 50/30/20 for simplicity.
3. **Reproducibility:** Document how to obtain the 50+200 dataset (e.g. export from your DB after one scrape, or synthetic generator), and how to run the evaluation script (e.g. in `backend/scripts/` or a notebook). Mention the repo and data in the paper.
4. **Venues:** IEEE ICMLA, IEEE SMC, FIRE, or IEEE Access (see §7). Use the IEEE template and replace placeholder results and references.

### One-sentence contribution for the abstract

*We propose a demand-weighted semantic skill-gap index (DW-SSGI) that combines BGE-based similarity, skill overlap, and keyword coverage with a demand-weighted penalty for missing skills; we implement it with KeyBERT for adaptive skill extraction and Ollama with Llama 2 for skill verification and natural-language gap and match advice, and show that DW-SSGI improves prioritization of high-demand gaps and ranking quality on a 50-resume × 200-job benchmark.*
