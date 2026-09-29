# 5–7 Day Research Paper Execution Plan

This plan supports the draft in `Demand_Weighted_Resume_Skill_Gap_Paper_Draft.md`.

---

## Day 2 — Baseline Scores

- [ ] Implement **Baseline 1:** Score = \( S \) (BGE cosine similarity only).
- [ ] Implement **Baseline 2:** Score = \( 0.7 S + 0.3 O \) (semantic + skill overlap).
- [ ] For each of 50 resumes, score against all 200 jobs; store rankings (e.g., CSV: resume_id, job_id, score_b1, score_b2).

---

## Day 3 — DW-SSGI and Proposed Ranking

- [ ] Implement \( D \) (demand-weighted gap) and full **DW-SSGI**: \( \alpha S + \beta O + \gamma K - \delta D \) (e.g., α=0.5, β=0.3, γ=0.2, δ=0.2).
- [ ] Compute proposed score for all 50×200 pairs; store ranking.
- [ ] **Ground truth:** If no labels, use Baseline 1 (semantic) ranking as surrogate relevance for Precision/Recall (or sample 10 resumes × 20 jobs for manual labels).

---

## Day 4 — Metrics and Tables

- [ ] Compute **Precision@K** and **Recall@K** (K=1,3,5,10) for Baseline 1, Baseline 2, Proposed (per resume, then average).
- [ ] Compute **Spearman correlation** between rankings (Baseline 2 vs. Proposed) per resume; report mean and std.
- [ ] Compute **demand alignment:** For each resume’s top-5 jobs, average \( \phi(s) \) over missing skills; average over resumes.
- [ ] Fill **Table I, II, III** in the paper draft with real numbers.

---

## Day 5 — Ablation and Figures

- [ ] **Ablation:** Run proposed with δ ∈ {0, 0.1, 0.2, 0.3}; fill Table II and plot Precision@5 and demand alignment vs. δ.
- [ ] **Ranking change:** Count % of resumes whose top-5 set changes vs. Baseline 2; fill Table III.
- [ ] **Figures:** Create Fig. 1 (pipeline), Fig. 2 (Precision/Recall bars), Fig. 3 (ablation plot), Fig. 4 (example gap report).

---

## Day 6 — Writing and References

- [ ] Replace all placeholder results (0.XX, XX%) in the draft with actual values.
- [ ] Shorten or expand Related Work with 5–10 real citations (Google Scholar: “resume job matching BERT”, “skill extraction job”, “demand skill labor market”).
- [ ] Polish Abstract, Introduction, and Conclusion to match the numbers.
- [ ] Run a spell/grammar check; ensure equation numbering and reference style (IEEE).

---

## Day 7 — Submission Prep

- [ ] Format with **IEEE conference template** (IEEEtran, two-column).
- [ ] Finalize author list, affiliations, and acknowledgments.
- [ ] Choose target: **IEEE ICMLA**, **IEEE SMC**, **FIRE**, or **IEEE Access** (open access, no deadline).
- [ ] Submit or send to co-authors for review.

---

## Minimal Code Hooks (Your Repo)

- **Embeddings:** `backend/app/services/embedding_service.py` (BGE).
- **Skills & demand:** `backend/app/services/skill_service.py` (`skill_demand_percentages` ≈ φ(s)).
- **Match score:** `backend/app/services/match_service.py` (S, O, K; add D and DW-SSGI in a script or notebook for the paper).

No new training; only evaluation scripts and the paper draft.
