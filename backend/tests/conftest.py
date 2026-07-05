"""Shared pytest fixtures.

Each DB-backed test gets a fully isolated Postgres database, Chroma dir, temp
upload dir, and mock embedding provider built through the same create_app()
factory the real app uses -- no monkeypatching of global state, no shared
state between tests. See python/fastapi.md testing rules and the
senior-project-pack modularity checklist (module testability).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.database import _normalise_async_database_url  # noqa: E402


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _base_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or Settings().database_url


@pytest_asyncio.fixture
async def postgres_database_url() -> AsyncIterator[str]:
    base_url = make_url(_normalise_async_database_url(_base_test_database_url()))
    database_name = f"test_{uuid4().hex}"
    maintenance_database = os.environ.get("TEST_POSTGRES_MAINTENANCE_DB", "postgres")
    maintenance_url = base_url.set(database=maintenance_database)
    test_url = base_url.set(database=database_name)

    admin_engine = create_async_engine(str(maintenance_url), isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE {_quote_identifier(database_name)}"))
    except Exception as exc:
        await admin_engine.dispose()
        pytest.skip(f"Postgres test database is unavailable: {exc}")

    try:
        yield str(test_url)
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "select pg_terminate_backend(pid) "
                    "from pg_stat_activity "
                    "where datname = :database_name and pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await conn.execute(
                text(
                    f"DROP DATABASE IF EXISTS {_quote_identifier(database_name)} "
                    "WITH (FORCE)"
                )
            )
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def test_settings(tmp_path: Path, postgres_database_url: str) -> Settings:
    return Settings(
        database_url=postgres_database_url,
        storage_backend="local",
        local_storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        auth_mode="disabled",
        embedding_provider="mock",
        llm_provider="mock",
        max_upload_bytes=10_485_760,
        max_direct_text_chars=200_000,
        chunk_size=1000,
        chunk_overlap=150,
    )


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client


@pytest.fixture
def wait_for_document_status():
    async def _wait(
        client: AsyncClient,
        document_id: str,
        *,
        status: str = "ready",
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_seen: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = await client.get("/documents", headers=headers)
            assert response.status_code == 200
            for item in response.json()["items"]:
                if item["document_id"] != document_id:
                    continue
                last_seen = item
                if item["status"] == status:
                    return item
            await asyncio.sleep(0.05)
        raise AssertionError(
            f"document {document_id} did not reach status={status!r}; last_seen={last_seen!r}"
        )

    return _wait
