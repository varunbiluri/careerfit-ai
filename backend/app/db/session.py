from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Create tables for FRESH installations only.

    create_all() is intentionally kept for zero-config local development: it
    creates every table that doesn't exist yet.  It will NOT alter existing
    tables (add columns, change types, etc.), so any schema change after the
    initial install MUST go through Alembic:

        uv run alembic upgrade head

    In production, run Alembic migrations as part of your deploy pipeline and
    remove the create_all() call (or guard it with an env flag).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
