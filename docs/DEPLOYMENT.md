# Deploying CareerFit AI

This guide covers a practical deployment setup for CareerFit AI. Recommended: **Render** for the backend and PostgreSQL, and **Vercel** for the frontend.

---

## Overview

| Component   | Where     | Notes |
|------------|-----------|--------|
| **Backend** | Render Web Service | FastAPI, BGE embeddings, LinkedIn scraping. Needs ≥ 1 GB RAM for BGE model. |
| **PostgreSQL** | Render PostgreSQL | Free tier available; use the **internal** URL for the backend. |
| **Frontend** | Vercel | React/Vite; set `VITE_API_URL` to your Render backend URL. |

---

## 1. Backend on Render

### 1.1 Create a PostgreSQL database

1. Go to [render.com](https://render.com) and sign in.
2. **New** → **PostgreSQL**.
3. Name it, for example `careerfit-ai-db`, choose a region, and select a plan.
4. Create. Copy the **Internal Database URL** (e.g. `postgresql://user:pass@host/dbname`).  
   For async SQLAlchemy you need `postgresql+asyncpg://...` — replace the first `postgresql://` with `postgresql+asyncpg://` and use that as `DATABASE_URL`.

### 1.2 Create a Web Service (backend API)

1. **New** → **Web Service**.
2. Connect your repo and select `careerfit-ai`.
3. Configure:
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:**  
     `pip install uv && uv sync`  
     (or use a `render.yaml`; see below.)
   - **Start Command:**  
     `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** BGE embeddings need roughly 1 GB+ RAM. If you see memory errors, use a larger plan or set `EMBEDDING_MODEL=all-MiniLM-L6-v2`.

### 1.3 Environment variables (Render Web Service)

In the Render dashboard → your Web Service → **Environment**:

| Key | Value |
|-----|--------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/dbname` (from step 1.1, internal URL with `+asyncpg`) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` (or `all-MiniLM-L6-v2` if on free tier and low memory) |
| `APP_NAME` | `CareerFit AI` |
| `LOG_LEVEL` | `INFO` |

Optional: `SCRAPER_DELAY_SECONDS=2`, `MAX_UPLOAD_MB=10`.

Save. Render will redeploy. Note the service URL, e.g. `https://your-backend.onrender.com`.

### 1.4 Health check

Open `https://your-backend.onrender.com/health`. You should see `{"status":"ok"}` (possibly after a cold start).

---

## 2. Frontend on Vercel

1. Go to [vercel.com](https://vercel.com) and import `careerfit-ai`.
2. **Root Directory:** `frontend`.
3. **Build Command:** `npm run build` (default).
4. **Environment variable:**
   - Name: `VITE_API_URL`  
   - Value: `https://your-backend.onrender.com` (no trailing slash; the frontend will call this as the API base).
5. Deploy. Vercel will give you a URL like `https://your-app.vercel.app`.

---

## 3. CORS

The backend is configured with `allow_origins=["*"]`, so your Vercel origin is allowed. If you later restrict origins, add your Vercel URL (e.g. `https://your-app.vercel.app`) to the list.

---

## 4. Optional: Render Blueprint (`render.yaml`)

In the **repo root** you can add `render.yaml` so Render can create both the DB and Web Service from one blueprint:

```yaml
services:
  - type: web
    name: careerfit-ai-api
    runtime: python
    region: oregon
    plan: free
    rootDir: backend
    buildCommand: pip install uv && uv sync
    startCommand: uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: careerfit-ai-db
          property: connectionString
      - key: EMBEDDING_MODEL
        value: BAAI/bge-small-en-v1.5
      - key: APP_NAME
        value: CareerFit AI

databases:
  - name: careerfit-ai-db
    plan: free
    region: oregon
```

**Note:** Render’s `connectionString` is usually `postgresql://...`. You must use `postgresql+asyncpg://...` for SQLAlchemy async. So either:
- Add a **script** in Render that sets `DATABASE_URL` from the DB and replaces `postgresql://` with `postgresql+asyncpg://`, or  
- Set `DATABASE_URL` manually in the dashboard to the internal URL with `+asyncpg`.

---

## 5. Deployment checklist

- [ ] Backend health: `https://your-backend.onrender.com/health` returns `{"status":"ok"}`.
- [ ] Frontend loads at your Vercel URL.
- [ ] Upload a resume PDF from the dashboard.
- [ ] Run **Analyze Skills Gap** and see fit %, gap %, matched/missing skills.
- [ ] Open a job and see resume–job match %).
- [ ] Add the live app link to your project README or portfolio.

---

## 6. Troubleshooting

| Issue | What to try |
|-------|------------------|
| Backend 503 / timeout on first request | Render free tier spins down after inactivity. First request may take 30–60 s; refresh. |
| Out of memory on backend | Use `EMBEDDING_MODEL=all-MiniLM-L6-v2` or upgrade to a paid plan with more RAM. |
| Frontend can’t reach API | Ensure `VITE_API_URL` is set to the **full** backend URL (e.g. `https://...onrender.com`) and has no trailing slash if your client adds paths correctly. |
| DB connection failed | Use the **internal** database URL (same region as the Web Service) and the `postgresql+asyncpg://` form. |
