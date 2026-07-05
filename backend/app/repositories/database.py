"""Async SQLAlchemy engine/session construction.

Deliberately exposes plain factory functions rather than a module-level
singleton engine: tests build their own isolated Postgres database through
the same functions the app uses, so no test needs to monkeypatch global state
or spin up the full app to exercise a repository. See senior-project-pack
modularity checklist, section 10.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _normalise_async_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    raise ValueError("DATABASE_URL must be a Postgres URL using postgresql+asyncpg.")


def build_engine(database_url: str) -> AsyncEngine:
    normalised_url = _normalise_async_database_url(database_url)
    return create_async_engine(normalised_url, echo=False, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
