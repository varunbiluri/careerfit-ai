# CareerFit AI Architecture

This document summarizes the main runtime components and data flow.

---

## Full-stack Flow

**Read top → bottom:** experience → API → intelligence → persistence → background → external data.

```mermaid
flowchart TB
  subgraph L1["1 — Client"]
    U[User]
    FE[React + TypeScript + Vite]
  end

  subgraph L2["2 — Edge"]
    NG[nginx — static UI + /api to backend]
  end

  subgraph L3["3 — Backend FastAPI + Uvicorn"]
    RT[HTTP API — auth · resumes · jobs · analysis · scraper]
    subgraph ML["ML / NLP inference"]
      BGE[BGE-small embeddings]
      KB[KeyBERT]
      COS[Cosine similarity + skill clustering]
    end
    subgraph DOM["Domain logic"]
      GAP[Gap + demand + top skills]
      MAT[Match scoring]
      RES[Resume PDF + skills]
      SCR[Job scrapers]
      LMC[LLM calls]
    end
  end

  subgraph L4["4 — Platform"]
    PG[(PostgreSQL)]
    RD[(Redis — cache + ARQ)]
    OL[(Ollama)]
    WK[ARQ worker]
  end

  subgraph L5["5 — External"]
    JB[Job boards]
  end

  U --> FE --> NG --> RT
  RT --> BGE
  RT --> KB
  RT --> GAP
  RT --> MAT
  RT --> RES
  RT --> SCR
  RT --> LMC
  BGE --> COS
  COS --> MAT
  COS --> GAP
  KB --> GAP
  RES --> GAP
  MAT --> PG
  GAP --> PG
  RES --> PG
  SCR --> PG
  SCR --> JB
  LMC --> OL
  BGE --> RD
  RT --> RD
  WK --> RD
  WK --> PG
```

## Runtime Summary

1. **Users** hit the **React** app; **nginx** serves the UI and forwards **`/api`** to **FastAPI**.
2. **Inference:** **BGE** vectors + **KeyBERT** phrases + **similarity** feed **match** and **gap** services.
3. **State** lives in **PostgreSQL**; **Redis** backs **embedding cache** and **ARQ** queues.
4. **Ollama** answers structured LLM calls (skill cleanup, gap/match advice) over HTTP.
5. **Scrapers** pull **job postings** from external boards; the **worker** can run heavy gap/scrape jobs asynchronously.

---

## Simplified block diagram (ASCII)

```
┌─────────────┐     ┌───────┐     ┌──────────────────────────────────────────┐
│   Browser   │────▶│ nginx │────▶│ FastAPI                                   │
│  React SPA  │     │ :80   │     │  routers → services (ML + business)     │
└─────────────┘     └───────┘     └───────┬───────────────┬─────────────────┘
                                          │               │
                    ┌─────────────────────┼───────────────┼─────────────────┐
                    ▼                     ▼               ▼                 ▼
              ┌───────────┐         ┌─────────┐   ┌───────────┐     ┌──────────┐
              │ PostgreSQL │         │  Redis  │   │  Ollama   │     │ Job board│
              │  primary   │         │cache+ARQ│   │ local LLM │     │ adapters │
              └───────────┘         └────┬────┘   └───────────┘     └──────────┘
                                         │
                                    ┌────▼────┐
                                    │ARQ worker│
                                    └─────────┘
```

---

*Aligned with `backend/app/` — routers, `embedding_service`, `skill_service`, `match_service`, `gap_service`, `resume_service`, `scraper_service`, `llm_service`, Redis cache, ARQ `worker/`.*
