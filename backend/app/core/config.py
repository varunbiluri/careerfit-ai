from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from backend directory so it's found regardless of cwd
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_path if _env_path.exists() else ".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")
    app_name: str = Field(default="CareerFit AI")
    debug: bool = Field(default=False)
    demo_mode: bool = Field(default=False, description="If True, skip live scraping and use deterministic corpus/synthetic fallback path")
    log_level: str = Field(default="INFO")
    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_resume_analyzer")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", description="SentenceTransformer model for resume-job similarity (e.g. BAAI/bge-small-en-v1.5, all-MiniLM-L6-v2)")
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # AI-based skill extraction (no dictionary): KeyBERT/keyphrase extraction — adaptive, detects unseen skills
    use_ai_skill_extraction: bool = Field(default=True, description="If True, use AI (KeyBERT) to extract skills from text; no fixed dictionary")
    use_dictionary_skill_extraction: bool = Field(default=False, description="If True, also run dictionary-based extraction and merge (optional fallback)")
    skill_extraction_top_n: int = Field(default=15, ge=1, le=100, description="Max key phrases to extract per document when use_ai_skill_extraction=True")
    skill_extraction_ngram_min: int = Field(default=1, ge=1, le=5, description="Min n-gram size for AI keyphrase extraction")
    skill_extraction_ngram_max: int = Field(default=3, ge=1, le=5, description="Max n-gram size for AI keyphrase extraction")
    # Semantic skill matching: treat job/market skill as "matched" if cosine_sim(embed(skill), embed(resume_skill)) > threshold
    use_semantic_skill_matching: bool = Field(default=True, description="If True, skills match by embedding similarity (e.g. REST API ≈ Backend API), not only exact name")
    semantic_skill_match_threshold: float = Field(default=0.8, ge=0.5, le=1.0, description="Legacy threshold when clustering disabled; clustering uses skill_cluster_similarity_threshold")
    skill_cluster_similarity_threshold: float = Field(
        default=0.85, ge=0.5, le=1.0,
        description="Cosine similarity for grouping skills into equivalence clusters (transitive union-find)",
    )
    skill_cluster_max_unique: int = Field(
        default=400, ge=50, le=5000,
        description="If unique(ref∪cand) skills exceed this, skip clustering and use exact match only (safety)",
    )
    scraper_user_agent: str = Field(default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CareerFit-AI/1.0")
    scraper_delay_seconds: float = Field(default=2.0, ge=1.0)
    scraper_cache_days: int = Field(default=7, ge=1)
    persist_scraped_jobs: bool = Field(
        default=False,
        description="If False, scraped LinkedIn jobs are kept in memory only (live_job_registry), not written to PostgreSQL.",
    )
    persist_resumes: bool = Field(
        default=False,
        description="If False, uploaded resume PDFs and extracted skills stay in memory only (live_resume_registry), not written to PostgreSQL.",
    )
    live_market_only: bool = Field(
        default=True,
        description=(
            "If True, gap analysis and job match use only in-memory scraped jobs for market demand "
            "(no PostgreSQL skill aggregates, corpus seed, or synthetic job fallbacks)."
        ),
    )
    # Previously hardcoded "India" in gap_service.py and worker/tasks.py.
    # Now configurable so non-India users get relevant market data.
    scraper_default_location: str = Field(default="India", description="Default location filter for job scraping (e.g. 'United States', 'Remote')")
    scraper_default_time_window_hours: int | None = Field(
        default=24,
        description="LinkedIn SERP time window (hours); passed as posted_within_hours. None = adapter default (still ~24h SERP).",
    )
    # Optional LinkedIn SERP filters (same semantics as typical n8n URL builders). Comma-separated labels.
    linkedin_scraper_experience_filter: str | None = Field(
        default=None,
        description="e.g. 'Mid-Senior level, Director' → f_E",
    )
    linkedin_scraper_remote_filter: str | None = Field(
        default=None,
        description="e.g. 'Remote, Hybrid' → f_WT",
    )
    linkedin_scraper_job_type_filter: str | None = Field(
        default=None,
        description="e.g. 'Full-time, Contract' → f_JT (first letter per segment)",
    )
    linkedin_scraper_easy_apply: bool = Field(
        default=False,
        description="If True, append f_EA=true to LinkedIn job search URLs",
    )
    linkedin_use_scrapling_fetcher: bool = Field(
        default=False,
        description=(
            "If True, fetch linkedin.com URLs with Scrapling AsyncFetcher (TLS/browser-like headers) "
            "before falling back to httpx. Improves guest job HTML quality; still respect LinkedIn ToS."
        ),
    )
    # How old scraped data can be before triggering a re-scrape.
    # Below this threshold the existing DB jobs are returned as-is.
    scrape_freshness_hours: float = Field(default=6.0, ge=0.5, description="Scraped jobs are considered fresh for this many hours; avoids hammering LinkedIn on every request")
    job_search_cache_ttl_seconds: int = Field(
        default=3600, ge=60, le=86400,
        description="TTL for in-process / Redis cache of job search scrape batches (1 hour default)",
    )
    job_corpus_seed_threshold: int = Field(
        default=100,
        ge=10,
        description="If DB has fewer jobs than this at startup, seed from data/job_corpus.json",
    )
    job_corpus_min_for_gap: int = Field(
        default=50,
        ge=1,
        description="During gap analysis, ensure at least this many jobs via corpus if scrape left DB sparse",
    )
    top_skills_live_job_sample_size: int = Field(
        default=5,
        ge=1,
        le=30,
        description=(
            "Live gap analysis: build 'Top skills to learn' from this many role-filtered jobs only "
            "(unique skills, frequency as demand % within the slice). Full-batch fit/missing_skills unchanged."
        ),
    )
    max_upload_mb: int = Field(default=10, ge=1)
    # CORS: '*' with allow_credentials=True is rejected by browsers (CORS spec).
    # Set to the actual frontend origin(s) for production.
    cors_allow_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins. Use explicit domains in production, never '*' with credentials.",
    )
    adzuna_app_id: str | None = Field(default=None, description="Adzuna API app ID for real job listings")
    adzuna_app_key: str | None = Field(default=None, description="Adzuna API app key")
    adzuna_country: str = Field(default="us", description="Adzuna country code: us, gb, etc.")
    # Local LLM (e.g. Ollama). Enables verified resume skills, AI summary, and gap/match advice. Set to empty to disable.
    llm_base_url: str | None = Field(default="http://localhost:11434", description="Local LLM base URL (e.g. http://localhost:11434 for Ollama); set empty to disable")
    llm_model: str = Field(default="llama3.2", description="Model name for local LLM (Ollama model name)")
    llm_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        description="HTTP read timeout for Ollama /api/generate; CPU-only servers often need 120s+",
    )
    llm_prompts_path: str | None = Field(default=None, description="Optional path to JSON file with prompt templates; else use built-in prompts")

    # ---------------------------------------------------------------------------
    # File logging + HTTP log viewer (panel demos — always use LOG_VIEWER_TOKEN)
    # ---------------------------------------------------------------------------
    log_file_path: str | None = Field(
        default=None,
        description="If set, append rotated file logging here (e.g. /var/log/ai-job-market/app.log). Needed for /logs/recent viewer.",
    )
    log_file_max_mb: int = Field(default=10, ge=1, le=100, description="Max size per log file before rotation")
    log_viewer_enabled: bool = Field(
        default=False,
        description="If True, expose GET /logs/recent?token= for read-only tail of log_file_path (disable after demo).",
    )
    log_viewer_token: str | None = Field(
        default=None,
        description="Secret query token required when log_viewer_enabled (use openssl rand -hex 16)",
    )
    log_viewer_max_lines: int = Field(default=400, ge=50, le=2000)

    # ---------------------------------------------------------------------------
    # Redis — set to empty string to disable Redis and ARQ entirely
    # ---------------------------------------------------------------------------
    redis_url: str = Field(
        default="",
        description="Redis connection URL (e.g. redis://localhost:6379/0). Empty = no Redis, no ARQ retries at startup.",
    )

    # ---------------------------------------------------------------------------
    # JWT authentication
    # ---------------------------------------------------------------------------
    jwt_secret_key: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        description="HMAC secret for JWT signing. Must be >=32 random bytes in production.",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, ge=1, description="JWT lifetime in minutes (default: 7 days)")

@lru_cache
def get_settings() -> Settings:
    return Settings()
