"""End-to-end API smoke for ingest -> retrieve -> answer -> persist."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ask_client(tmp_path: Path, postgres_database_url: str) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url=postgres_database_url,
        storage_backend="local",
        local_storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        auth_mode="jwt",
        jwt_secret="integration-test-secret-not-for-real-use",
        admin_emails="ask-flow@example.com",
        embedding_provider="mock",
        llm_provider="mock",
        retrieval_min_similarity=0.0,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_authenticated_ingest_to_ask_flow_persists_answer(
    ask_client: AsyncClient, wait_for_document_status
):
    register = await ask_client.post(
        "/auth/register",
        json={"email": "ask-flow@example.com", "password": "correct-password"},
    )
    assert register.status_code == 201
    token = register.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    upload = await ask_client.post(
        "/documents",
        data={
            "title": "NICE hypertension access evidence",
            "text": (
                "Document ID: nice_htn_001\n"
                "Country: United Kingdom\n"
                "Language: English\n\n"
                "NICE recommended routine access for the hypertension medicine "
                "after reviewing the cost-effectiveness evidence."
            ),
            "country": "United Kingdom",
            "language": "English",
        },
        headers=auth_headers,
    )
    assert upload.status_code == 202
    uploaded = upload.json()
    assert uploaded["status"] == "processing"
    await wait_for_document_status(
        ask_client,
        uploaded["document_id"],
        headers=auth_headers,
    )

    answer = await ask_client.post(
        "/ask",
        json={
            "question": "What did NICE conclude about routine access?",
            "country": "United Kingdom",
        },
        headers=auth_headers,
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["answer"]
    assert body["sources"]
    assert body["sources"][0]["source_id"] == "UK-NICE-001"
    assert body["sources"][0]["document_title"] == "NICE hypertension access evidence"
    assert body["confidence"] in {"high", "medium", "low"}

    app = ask_client._transport.app
    assert app.state.vector_store._collection is app.state.retriever._collection
    session_factory = app.state.session_factory
    async with session_factory() as session:
        saved_answers = await session.execute(text("select count(*) from answers"))
        saved_sources = await session.execute(text("select count(*) from answer_sources"))

    assert saved_answers.scalar_one() == 1
    assert saved_sources.scalar_one() >= 1
