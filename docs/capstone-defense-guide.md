# Capstone defense guide — CareerFit AI

Use this to rehearse. Timebox: **10–15 minutes talk + 5–10 minutes Q&A** (adjust to your panel rules).

**Presenter:** B. Sai Vignesh · Supervisors: Dr. B. Bhaskara Rao, Ms. R. Arshiya

---

## 1. How to open (≈ 45 seconds)

**Say:**

> “Good morning / afternoon. I’m presenting my capstone: **CareerFit AI** — a full-stack system that compares a candidate’s resume against **live job postings**, uses **transformer embeddings** and **skill extraction** to find gaps, and ranks **what to learn next** using **market demand**, not just keyword overlap.
>
> I’ll walk through the problem and approach, the **research and methods** behind it, a **live demo** on our deployed server, then briefly show the **codebase** in VS Code and **service logs**. I’m happy to take questions at the end.”

*Breathe. Don’t read slides word-for-word.*

---

## 2. What to say slide-by-slide (compressed script)

| Section | What to say (your words) |
|--------|---------------------------|
| **Problem** | Resume tools often match **keywords** or one **similarity score**. They miss **which missing skills hurt most in the market** and give **little explanation**. |
| **Abstract / vision** | We combine **NLP**, **pretrained embeddings** (SentenceTransformers), **keyphrase extraction** (KeyBERT-style), and **demand statistics** from scraped jobs. Output: **fit score**, **matched/missing skills**, **top skills to learn**, and **LLM-assisted** explanations via **Ollama** (local). |
| **Users & use cases** | Primary user is the **job seeker**; secondary is **placement/training** (where to focus upskilling). |
| **Data** | **Resume PDFs** → text → skills. **Job postings** from configured sources → skills and **demand %**. Everything is tied to a **target role**. |
| **Methods** | Parsing → skill extraction → **semantic similarity** vs job text → **overlap** → **composite score** with **demand penalty** on hot missing skills. |
| **Tech** | **React** frontend, **FastAPI** backend, **PostgreSQL**, **Redis + ARQ** for async jobs and cache, **Ollama** for LLM, **nginx** on the VM for production. |
| **Results / features** | Dashboard shows **gap analysis**, **top skills to learn**, **trends**, **job matches**, **structured advice**. |
| **Pipeline** | Upload PDF → extract skills → analyze gap (market jobs + scoring) → optional LLM verification of noisy skill phrases. |
| **Limitations** | Market view depends on **scraped volume** and **time window**; not a government labor survey. We document **bias** and **mitigations** (multi-source, filters, re-scrape). |

---

## 3. What “research” you can claim (be honest, be precise)

You are **not** training a foundation model from scratch. Your **research contribution** is **applied ML / NLP + systems**:

1. **Representation learning (inference)**  
   - Use **pretrained** sentence embeddings (**BGE-small**) to compare resume and job text **semantically** (cosine similarity).  
   - *Reference area:* sentence embeddings for semantic textual similarity (Sentence-BERT family, general embedding literature).

2. **Unsupervised keyphrase extraction**  
   - **KeyBERT** (or equivalent) over resume/job text to surface skill-like phrases, plus **rules/blocklists** to reduce noise.  
   - *Reference area:* keyphrase extraction, domain adaptation without large labeled resume–job pairs.

3. **Explainable composite scoring**  
   - Combine **semantic**, **skill overlap**, **keyword**, and **demand-based penalty** so the score is **interpretable** (weights visible in the app).  
   - *Reference area:* explainable AI / multi-criteria ranking for HR-tech (cite as *design choice + evaluation*, not a new theorem).

4. **Market-grounded gap analysis**  
   - Derive **demand %** from aggregated postings; prioritize **high-demand missing** skills; optionally **LLM** filters for **technical, learnable** items (Ollama).  
   - *Reference area:* labor market signals from web data (with limitations).

5. **Engineering / deployment research**  
   - End-to-end **production-style** stack: API, DB, cache, worker, reverse proxy, **VM deployment** — **reproducible** demo.

**If asked “What is novel?”**  
Say: *“The novelty is **integrating** embedding-based matching, keyphrase-based skills, **demand-weighted** gap ranking, and **local LLM** verification in one **deployable** product, with **explainable** score components—not inventing a new base model.”*

---

## 4. Demo order (recommended)

**Goal:** Show **working product first**, then **credibility** (code + logs).

### A. Live deployment (2–4 minutes) — **primary**

1. Open browser → **VM URL** (e.g. `http://<IP>/`).  
2. Show **landing → dashboard** (or login if required).  
3. **Upload a sample PDF** (or use existing session).  
4. Set **target role** (e.g. Machine Learning Engineer).  
5. Run **Analyze** / gap analysis.  
6. Point to: **market fit %**, **matched vs missing skills**, **top skills to learn**, **one job match** if time.

**Say while clicking:**  
> “Here the backend pulls **role-relevant** job data, extracts skills, computes **embedding-based** similarity and **demand-weighted** gaps. The **top skills** list is grounded in **recent postings** and filtered with **heuristics plus our local LLM**.”

### B. VS Code — **structure, not line-by-line** (2–3 minutes)

1. Open repo **`AI Job Market`**.  
2. Expand **`backend/app/services/`** — name **`embedding_service`**, **`skill_service`**, **`match_service`**, **`gap_service`**, **`llm_service`**.  
3. Open **`match_service.py`** — scroll to **weight constants** (semantic / overlap / keyword / demand penalty) — **30 seconds**.  
4. Optional: **`gap_service.py`** — one sentence: *“orchestrates scrape freshness, gap computation, LLM advice.”*

**Say:**  
> “The logic lives in **services**; FastAPI **routers** are thin. Scoring weights are **explicit** here so the UI can explain the number.”

### C. Logs on the VM — **proof the system runs** (1–2 minutes)

**Before the session, SSH and run** (or have a terminal tab ready):

```bash
ssh -i ~/Downloads/vm-dev.pem vignesh@your-server.example.com
sudo journalctl -u ai-job-market-api -n 40 --no-pager
```

**Say:**  
> “This is the **API service log** on the server: startup, database, requests. If we trigger an analysis live, you’ll see the **request** and **timing** here.”

**Browser log tail (judges on Wi‑Fi):** With `LOG_FILE_PATH`, `LOG_VIEWER_ENABLED=true`, and `LOG_VIEWER_TOKEN` set on the VM:

- **Live (auto-refresh, no F5):**  
  `https://your-careerfit-ai-api.example.com/api/logs/watch?token=<YOUR_TOKEN>&lines=300`  
  The page polls `/api/logs/recent` every few seconds.

- **One-shot plain text:**  
  `https://your-careerfit-ai-api.example.com/api/logs/recent?token=<YOUR_TOKEN>&lines=200`

Same nginx host as the app (no SSH). **Turn off** `LOG_VIEWER_ENABLED` after the panel.

**Optional:** `sudo tail -20 /var/log/nginx/error.log` only if you need to show **nginx** health (usually skip unless asked).

---

## 5. Expected questions & short answers

### Problem & scope

| Question | Answer direction |
|----------|------------------|
| Why not only keyword matching? | Keywords miss **synonyms** and **context**; embeddings capture **meaning**; we still use keywords as one **explicit** signal. |
| What is “real-time market demand”? | **Demand %** is computed from **our scraped job sample** in a **configurable** window/region—not a national statistic. |
| Who is the user? | **Job seekers** first; **placement cells** can use aggregates for **training focus**. |

### Technical / ML

| Question | Answer direction |
|----------|------------------|
| Which embedding model? | **BAAI/bge-small-en-v1.5** (SentenceTransformers)—**pretrained**; we use it for **inference** only. |
| How do you extract skills? | **KeyBERT**-style keyphrases + **normalization** + **blocklists**; optional **LLM** to clean phrases. |
| How is the final score built? | **Weighted sum**: semantic + skill overlap + keyword − **demand penalty** on high-demand missing skills; weights are in **code** and reflected in the UI. |
| Did you train a model? | **No** end-to-end training of a new LM; we use **pretrained** embeddings and **engineered** scoring + filters. |
| Why Ollama? | **Local** LLM: **privacy**, **no API key** for demos, **verification** of noisy skill strings and **structured advice**. |

### Data & ethics

| Question | Answer direction |
|----------|------------------|
| Is scraping legal / ethical? | We use **public job listings** with **rate limits** and **caching**; production use should follow **site ToS** and **robots** policy—we acknowledge **limitations** in the report. |
| Bias in data? | Scraped data can **skew** by platform and region; we state **limitations** and suggest **multi-source** and **refresh** as future work. |

### Engineering

| Question | Answer direction |
|----------|------------------|
| Why FastAPI + React? | **FastAPI** for async I/O and OpenAPI docs; **React** for a modern **SPA** dashboard. |
| What is Redis for? | **Embedding cache** and **ARQ** queue for **background** gap jobs when enabled. |
| How is it deployed? | **systemd** runs the API; **nginx** serves the **built frontend** and **proxies** `/api` to the backend. |

### Evaluation

| Question | Answer direction |
|----------|------------------|
| How do you evaluate quality? | **Qualitative**: sensible skills, stable scores, **explainability**. **Quantitative** future work: labeled pairs or expert ratings—we mention this as **future work** if not done. |
| Comparison to baselines? | Baseline could be **keyword-only** or **embedding-only**; our system **combines** signals + **demand**—position as **ablation** in thesis if you ran experiments. |

---

## 5b. Cross-examination: what lecturers often probe (use with §5)

Panels **will** ask follow-ups. Pattern: **acknowledge limitation → say what you did instead → what you would do with more time**. Do not argue that scraped data is “ground truth.”

### Validity & “is this scientifically sound?”

| Likely question | How to answer |
|-----------------|----------------|
| **Your demand % is not a real labor statistic—so what is it?** | It is a **sample statistic** over **our job corpus** (scraped + cached postings), normalized to percentages. It shows **relative frequency** in that slice, not national employment. We label it that way in the UI and thesis. |
| **How many jobs is that based on? Can we trust it?** | The system uses **up to dozens of role-relevant postings** per analysis (config/caps in code). More jobs → stabler demand estimates; **sparse data** lowers confidence—we expose **confidence-style** logic (corpus size, skill counts) rather than hiding uncertainty. |
| **Why these weights (50% semantic, 30% overlap, 20% keyword, 20% demand penalty)?** | They are **explicit design constants** in `match_service.py` so the score is **interpretable** and **tunable**. The capstone contribution is the **framework**, not claiming these weights are globally optimal—**future work** is sensitivity analysis or learning weights from feedback. |
| **Did you prove this score predicts hiring success?** | **No**—we do not have hire/offer labels. We position the system as **decision support** and **gap prioritization**, not a certified hiring test. Evaluation is **qualitative** + **sanity checks** unless you ran formal experiments (say so honestly). |

### Methods & “why not X?”

| Likely question | How to answer |
|-----------------|----------------|
| **Why BGE-small and not a larger model?** | **Latency and deployment** on a VM; **small** embedding models are standard for semantic similarity; we trade a few points of accuracy for **speed** and **resource use**. |
| **Keyword vs embedding—why both?** | **Embeddings** handle paraphrase; **keywords** give an **auditable** lexical signal employers still use in JDs. **Both** reduce single-source blind spots. |
| **Is KeyBERT enough for skills?** | It proposes **candidates**; we add **normalization**, **dictionaries/blocklists**, and optional **LLM cleanup**—so extraction is **hybrid**, not raw KeyBERT only. |

### Ethics, privacy, scraping

| Likely question | How to answer |
|-----------------|----------------|
| **Resume data—where does it live?** | **User-associated storage** in our app model (authenticated flows); for the defense, state what you actually deployed: **not** public by default. Do **not** claim GDPR compliance unless you implemented it—say **good practice**: HTTPS, access control, **delete path** as future hardening if not done. |
| **Scraping job sites?** | We **rate-limit**, **cache**, and treat it as **research/education** with **limitations** in the report. Production would require **official APIs** or **licensed feeds** where available. |

### Scope & novelty (they test humility)

| Likely question | How to answer |
|-----------------|----------------|
| **What exactly did *you* implement vs libraries?** | **Integration and system design**: orchestration (FastAPI, DB, Redis/ARQ), **scoring and gap logic**, **normalization**, **deployment**. We **do not** claim we invented BGE or KeyBERT. |
| **What fails in practice?** | **Thin market** for a niche role → fewer jobs → weaker demand estimates; **noisy** postings; **LLM** optional—if Ollama is down, core numeric gap analysis still runs. |

### One-liner if they press for “one weakness”

> “The main limitation is **evaluation without labeled hire outcomes**—we optimize for **transparent, market-grounded prioritization**, not proven recruitment validity.”

---

## 5c. Pushback: “This is not machine learning” or “not deep learning”

Panels sometimes equate “ML project” only with **training a large model from scratch**. Your answer should be **calm, precise, and one sentence of humility**.

### What is true (say this)

1. **Machine learning** includes **inference** with **pretrained** models, not only training. Industry and academia both call that **applied ML** or **transfer learning**.  
2. **Deep learning is already in the stack (inference):**  
   - **BGE / SentenceTransformers** models are **transformer-based** neural networks; every embedding vector is a **forward pass** through that network (typically **PyTorch**).  
   - **KeyBERT** uses **BERT-style** representations (again, deep architectures).  
   - **Ollama** runs a **large language model**—that is **deep learning** at inference time.  
3. Your **contribution** is **not** a new architecture, but an **integrated system**: combining **representation-based similarity**, **keyphrase extraction**, **demand-aware ranking**, and **LLM-assisted** cleanup in a **deployable** product with **explainable** scores.

### Short script (≈ 45 seconds)

**Say:**

> “I agree we are **not** training a foundation model from random initialization—that wasn’t the goal. The project **does** use **machine learning** in the standard sense: we run **pretrained deep neural networks** for **sentence embeddings** and use **BERT-family** signals for **keyphrase extraction**, and we optionally call a **local LLM**—all of that is **deep learning at inference**.  
>  
> The **research angle** here is **applied ML / NLP**: how to **combine** these representations with **market statistics** and **transparent scoring** so users get **actionable** gaps, not a black-box percentage. If the committee prefers the label **‘intelligent systems’** or **‘NLP + IR’**, I’m comfortable with that too—the methods are still **ML-based**.”

### If they press: “Then it’s only software engineering”

**Say:**

> “The **software** carries the **ML components**. Without embeddings, keyphrase models, and the scoring design, it would be a CRUD app. The **intellectual work** is **choosing and integrating** these methods for skill-gap analysis and **evaluating** limitations—that’s why we frame it as **applied ML**, not pure web development.”

### Optional one-liner (if time is short)

> “**Deep learning runs inside our embedding and LLM calls—we use pretrained networks; we don’t retrain the full stack from scratch.**”

---

## 6. If something breaks during demo

1. **Stay calm.** Say: *“The live service depends on network and cached job data; I’ll show the **same flow** from logs / a screenshot backup.”*  
2. Have **one screenshot** of a successful analysis in the deck as **backup**.  
3. **VS Code** still proves **implementation**.

---

## 7. Closing line (≈ 20 seconds)

**Say:**

> “To summarize: this project delivers an **explainable, market-aware skill gap analyzer** using **pretrained embeddings**, **keyphrase extraction**, **demand-weighted scoring**, and a **local LLM**, packaged as a **deployable web application**. Thank you — I’m ready for questions.”

---

## 8. Checklist the day before

- [ ] VM reachable; **Ollama** running if you demo LLM features.  
- [ ] **Sample PDF** ready; **target role** chosen.  
- [ ] Browser **cache cleared** or incognito to avoid stale UI.  
- [ ] **journalctl** command tested.  
- [ ] Slides export to PDF **backup** on USB / phone.  
- [ ] Time yourself: **talk & demo under panel limit**.

---

*This guide matches the repository architecture and your “Cream and Pink Leaves” deck content. Adjust names and IP addresses before sharing.*
