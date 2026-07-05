"""Shared pytest fixtures.

Each test gets a fully isolated app instance (temp SQLite file, temp
Chroma dir, temp upload dir, mock embedding provider) built through the
same create_app() factory the real app uses -- no monkeypatching of global
state, no shared state between tests. See python/fastapi.md testing rules
and the senior-project-pack modularity checklist (module testability).
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
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
