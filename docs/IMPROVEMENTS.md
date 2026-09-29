# Improvement Ideas — AI, Data Science & Visualization

This doc lists ways to improve the **CareerFit AI** using **AI/ML**, **data science**, and **visualization**. Use what fits your capstone scope and time.

---

## 1. AI / ML improvements

| Area | Current | Improvement | Why it matters |
|------|--------|-------------|----------------|
| **Skill extraction** | Dictionary-only (`skills_dictionary.json`): if a skill isn’t in the list, it’s missed. | Add **embedding-based** or **NER-based** extraction: e.g. embed resume sentences and compare to embeddings of skill phrases, or use a small NER model to tag skills. | Catches skills not in the dictionary and improves gap accuracy. |
| **Resume summary** | None. | Optional **LLM summary**: “Strengths”, “Gaps vs market”, “1–2 sentence pitch” (e.g. OpenAI/Anthropic or local LLM). | Better storytelling for the user; strong capstone demo. |
| **Job clustering** | Jobs are a flat list. | **Cluster jobs by embedding** (e.g. K-means on job description embeddings), label clusters (e.g. “Data Science”, “Backend”), show “Your fit by cluster”. | Data science + ML; shows “where you fit” in the market. |
| **Skill normalization** | Exact string match (e.g. “Python” vs “Python 3”). | **Embedding similarity** for skill matching: map resume/job skills to a canonical set via nearest-neighbor in embedding space. | Fewer missed matches due to wording. |
| **Demand over time** | Demand is point-in-time (current DB). | Store **scrape timestamps** per job; compute demand % over time; optional **simple trend** (e.g. linear regression or moving average). | Data science narrative: “Skill X is growing in demand.” |

---

## 2. Data science & analytics

| Area | Current | Improvement | Why it matters |
|------|--------|-------------|----------------|
| **Market overview** | None. | **Aggregate API**: top N skills by demand, job count by seniority/function (you already extract these in the scraper). Expose as `/analysis/market-summary` or similar. | Feeds dashboards and “market snapshot” viz. |
| **Resume vs market** | Fit % and lists (matched/missing). | **Structured comparison**: e.g. table or radar of “resume level” vs “market level” per skill category (if you add categories). | Clear data story. |
| **Match score breakdown** | Backend returns 50/30/20 (semantic, skill, keyword) but UI doesn’t visualize it. | **Pie or bar chart** of the three components when user views “Match” for a job. | Makes the scoring transparent and educational. |
| **High-demand missing** | Shown as cards; you have a bar chart component. | **Bar chart** of “high-demand missing skills” (demand % or job count). | Recharts already in project; stronger data viz. |
| **Job landscape** | Jobs as list. | **2D embedding plot**: reduce job embeddings to 2D (PCA/t-SNE/UMAP), plot jobs; optionally show “your resume” as a point. | Strong data science + ML capstone piece (backend: compute 2D coords; frontend: scatter plot). |

---

## 3. Visualization (frontend)

| Viz | Data source | Component / idea | Priority |
|-----|-------------|------------------|----------|
| **High-demand missing skills (bar)** | `gapResult.high_demand_missing_skills` | Use existing `SkillDemandChart` in the gap result section. | High — quick win. |
| **Match score breakdown (50/30/20)** | `MatchResult.resume_score` (semantic, skill_overlap, keyword_coverage) | Pie chart or horizontal bar when user clicks “Match” for a job (need resume selector + match API call). | High — explains the model. |
| **Market fit (radar)** | Resume skills vs market skills by category | Radar: axes = skill categories, values = coverage. Needs backend to return per-category counts or a dedicated endpoint. | Medium. |
| **Market overview** | New `/analysis/market-summary` (or reuse skill-demand + job list) | Top skills bar chart; job count by seniority/function (pie or bar). | Medium. |
| **Job landscape (2D)** | New endpoint returning job_id, x, y (from PCA/t-SNE on embeddings) | Scatter plot (e.g. Recharts or a scatter lib); optional “resume” point. | Nice-to-have. |

---

## 4. Suggested order of work

1. **Quick wins (no new backend)**  
   - Use **SkillDemandChart** for `high_demand_missing_skills` in the gap result.  
   - Add **match breakdown** (pie/bar) when user selects a resume and clicks “Match” on a job (call existing `/analysis/match`).

2. **Backend analytics**  
   - Add **market summary** endpoint (top skills, counts by seniority/function) and a small **Market overview** section with charts.

3. **AI**  
   - **Skill extraction**: add an optional embedding-based pass to find skills not in the dictionary.  
   - **Job clustering**: cluster jobs by embedding, label and show “fit by cluster”.

4. **Advanced**  
   - **Resume summary** (LLM); **demand over time** (store scrape date, add trend); **2D job landscape** (PCA/t-SNE + scatter).

---

## 5. Tech notes

- **Charts:** Project already uses **Recharts**; use it for bar, pie, line, and (with a little work) scatter.  
- **Backend ML:** Keep using **sentence-transformers** (BGE) for embeddings; add **scikit-learn** for K-means, PCA (already in deps).  
- **LLM:** Optional; use API (OpenAI/Anthropic) or a local model; keep it behind a feature flag or env var so the app runs without it.

Using **AI** (embeddings, NER, optional LLM) and **data science** (aggregations, clustering, trends) plus **visualization** (Recharts) will make the capstone clearly “AI + data science” and easier to demo.
