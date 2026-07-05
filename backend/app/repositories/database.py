"""Async SQLAlchemy engine/session construction.

Deliberately exposes plain factory functions rather than a module-level
singleton engine: tests build their own isolated engine (temp-file or
in-memory SQLite) through the same functions the app uses, so no test needs
to monkeypatch global state or spin up the full app to exercise a
repository. See senior-project-pack modularity checklist, section 10.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    path_part = database_url.split("///", 1)[-1]
    if path_part and path_part != ":memory:":
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str) -> AsyncEngine:
    _ensure_sqlite_parent_dir(database_url)
    return create_async_engine(database_url, echo=False)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            result = await conn.execute(text("PRAGMA table_info(users)"))
            columns = {row[1] for row in result.fetchall()}
            if "is_admin" not in columns:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
                )
