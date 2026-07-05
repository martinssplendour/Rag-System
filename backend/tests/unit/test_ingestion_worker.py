from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.constants import INGESTION_JOB_FAILED, INGESTION_JOB_PENDING, STATUS_FAILED
from app.repositories.database import build_engine, build_session_factory, create_all
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_jobs import IngestionJobRepository
from app.services import document_service
from app.services.ingestion_worker import process_next_ingestion_job
from app.storage.local import LocalStorageProvider


@pytest.mark.anyio
async def test_ingestion_worker_retries_before_final_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="market_access_evidence_assistant")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'retry.db').as_posix()}",
        local_storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        embedding_provider="mock",
        llm_provider="mock",
        ingestion_job_max_attempts=2,
    )
    engine = build_engine(settings.database_url)
    await create_all(engine)
    session_factory = build_session_factory(engine)
    storage = LocalStorageProvider(settings.local_storage_dir)
    vector_store = FakeVectorStore()

    async with session_factory() as session:
        document = await document_service.create_document(
            session=session,
            workspace_id=settings.default_workspace_id,
            storage=storage,
            settings=settings,
            file=None,
            text="Evidence body that will fail during embedding.",
            title="Retry document",
        )
        document_id = document.id

    first_processed = await process_next_ingestion_job(
        session_factory=session_factory,
        storage=storage,
        embedding_provider=FailingEmbeddingProvider(),
        vector_store=vector_store,
        settings=settings,
    )
    assert first_processed is True

    async with session_factory() as session:
        job = await IngestionJobRepository(session).get_latest_for_document(document_id)
        document = await DocumentRepository(session).get(settings.default_workspace_id, document_id)
        assert job is not None
        assert document is not None
        assert job.status == INGESTION_JOB_PENDING
        assert job.attempts == 1
        assert document.status == "processing"

    second_processed = await process_next_ingestion_job(
        session_factory=session_factory,
        storage=storage,
        embedding_provider=FailingEmbeddingProvider(),
        vector_store=vector_store,
        settings=settings,
    )
    assert second_processed is True

    async with session_factory() as session:
        job = await IngestionJobRepository(session).get_latest_for_document(document_id)
        document = await DocumentRepository(session).get(settings.default_workspace_id, document_id)
        assert job is not None
        assert document is not None
        assert job.status == INGESTION_JOB_FAILED
        assert job.attempts == 2
        assert job.error_message == "Ingestion failed; see server logs for details."
        assert document.status == STATUS_FAILED
        assert document.error_message == "Ingestion failed; see server logs for details."

    await engine.dispose()
    assert vector_store.deleted_document_ids == [document_id, document_id, document_id, document_id]
    log_messages = [record.getMessage() for record in caplog.records]
    assert any("ingestion_job_retrying" in message for message in log_messages)
    assert any("ingestion_job_failed_final" in message for message in log_messages)


class FailingEmbeddingProvider:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise RuntimeError("provider stack trace and secret path should stay server-side")

    async def embed_query(self, text: str) -> list[float]:
        del text
        raise NotImplementedError


class FakeVectorStore:
    def __init__(self) -> None:
        self.deleted_document_ids: list[str] = []

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        del chunks

    def delete_by_document(self, document_id: str) -> None:
        self.deleted_document_ids.append(document_id)
