# CareerFit AI

CareerFit AI is an open-source career intelligence app that analyzes a resume against live job-market signals and turns skill gaps into clear learning priorities.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Author

**Varun Billuri**

## Features

- Upload a PDF resume and extract candidate skills.
- Compare resume skills with job-market demand.
- Calculate resume-to-job match scores with explainable breakdowns.
- Identify high-demand missing skills to learn next.
- Generate optional AI summaries and advice with a local LLM.
- Run as a full-stack product with a React frontend and FastAPI backend.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind CSS, Recharts |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| Data | PostgreSQL, JSON seed data |
| AI/ML | Sentence Transformers, BGE embeddings, KeyBERT, optional Ollama |
| Optional infra | Redis, ARQ background jobs |

## Project Structure

```text
careerfit-ai/
├── backend/      # FastAPI API, services, models, migrations, tests
├── frontend/     # React/Vite frontend
├── docs/         # Product documentation
├── LICENSE
├── CONTRIBUTING.md
└── SECURITY.md
```

## Quick Start

### Backend

```bash
cd backend
uv venv
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Backend URLs:

- API: `http://127.0.0.1:8000`
- Swagger docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL:

- App: `http://localhost:5173`

For local development, the frontend defaults to `/api`. For deployed environments, set:

```text
VITE_API_URL=https://your-backend-url.example.com
```

## Deployment

Recommended production-style setup:

- **Frontend:** Vercel
- **Backend:** Render, Railway, Fly.io, or a VM
- **Database:** PostgreSQL

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for deployment notes.

## Configuration

Important backend environment variables live in [backend/.env.example](backend/.env.example).

For a simple demo deployment, you can start with:

```text
APP_NAME=CareerFit AI
DEBUG=false
PERSIST_RESUMES=false
PERSIST_SCRAPED_JOBS=false
LIVE_MARKET_ONLY=true
LLM_BASE_URL=
```

Add PostgreSQL, Redis, and Ollama when you need persistence, background jobs, or local AI-generated advice.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Local LLM and prompts](docs/LOCAL_LLM_AND_PROMPTS.md)

## Development Checks

Backend:

```bash
cd backend
PYTHONPATH=. uv run --extra dev python -m pytest
```

Frontend:

```bash
cd frontend
npm run build
```

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

CareerFit AI is released under the [MIT License](LICENSE).
