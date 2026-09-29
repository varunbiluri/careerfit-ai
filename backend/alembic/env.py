"""
Alembic async migration environment for SQLAlchemy 2.x + asyncpg.

Run migrations:
    uv run alembic upgrade head

Generate a new revision after changing models:
    uv run alembic revision --autogenerate -m "short description"

The DATABASE_URL is read from the application Settings (respects .env) so there
is no duplication of the connection string here.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Alembic Config object (provides access to alembic.ini values)
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so their tables appear in Base.metadata
from app.db.base import Base  # noqa: E402
from app.models import Job, Resume, Skill, User  # noqa: E402, F401

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Read DATABASE_URL from application settings (honours .env file)."""
    from app.core.config import get_settings
    url = get_settings().database_url
    # asyncpg driver prefix is correct for runtime but alembic needs the
    # synchronous form for offline mode; keep async form for online mode.
    return url


# ---------------------------------------------------------------------------
# Offline mode — emit SQL to stdout without a live DB connection
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    url = _get_database_url()
    # Replace async driver with sync one for offline SQL generation
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connect to DB and run migrations
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _get_database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # one-shot connection, no pool needed for CLI
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
