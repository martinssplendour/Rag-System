from __future__ import annotations

import pytest

from app.repositories.database import _normalise_async_database_url


def test_normalise_postgres_urls_to_asyncpg() -> None:
    assert (
        _normalise_async_database_url("postgres://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )
    assert (
        _normalise_async_database_url("postgresql://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )


def test_normalise_database_url_leaves_explicit_async_postgres_url_unchanged() -> None:
    assert (
        _normalise_async_database_url("postgresql+asyncpg://user:pass@db:5432/app")
        == "postgresql+asyncpg://user:pass@db:5432/app"
    )


def test_normalise_database_url_rejects_non_postgres_urls() -> None:
    with pytest.raises(ValueError, match="Postgres"):
        _normalise_async_database_url("mysql+asyncmy://user:pass@db:3306/app")
