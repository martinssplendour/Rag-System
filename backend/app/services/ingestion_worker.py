from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.constants import (
    SOURCE_TYPE_DOCX,
    SOURCE_TYPE_PDF,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
)
from app.rag.embeddings import EmbeddingProvider
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_jobs import IngestionJobRepository
from app.services.ingestion_service import DocumentContext, ingest_document
from app.storage.base import StorageProvider
from app.vectorstores.base import VectorStore

logger = logging.getLogger("kintiga_evidence_assistant")


class IngestionWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: StorageProvider,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def run_forever(self) -> None:
        poll_seconds = max(float(self._settings.ingestion_worker_poll_seconds), 0.05)
        while True:
            processed = await process_next_ingestion_job(
                session_factory=self._session_factory,
                storage=self._storage,
                embedding_provider=self._embedding_provider,
                vector_store=self._vector_store,
                settings=self._settings,
            )
            if not processed:
                await asyncio.sleep(poll_seconds)


async def process_next_ingestion_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageProvider,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    settings: Settings,
) -> bool:
    job_id = await _claim_next_job(session_factory)
    if job_id is None:
        return False
    await process_ingestion_job(
        job_id,
        session_factory=session_factory,
        storage=storage,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        settings=settings,
    )
    return True


async def process_ingestion_job(
    job_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageProvider,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    settings: Settings,
) -> None:
    try:
        async with session_factory() as session:
            await _run_job_in_session(
                job_id,
                session=session,
                storage=storage,
                embedding_provider=embedding_provider,
                vector_store=vector_store,
                settings=settings,
            )
    except Exception:
        logger.exception("ingestion_job_failed job_id=%s", job_id)
        await _handle_job_failure(
            job_id,
            session_factory=session_factory,
            vector_store=vector_store,
            max_attempts=max(int(settings.ingestion_job_max_attempts), 1),
            error_message="Ingestion failed; see server logs for details.",
        )


async def _claim_next_job(session_factory: async_sessionmaker[AsyncSession]) -> str | None:
    async with session_factory() as session:
        repo = IngestionJobRepository(session)
        job = await repo.claim_next_pending()
        if job is None:
            return None
        job_id = job.id
        await session.commit()
        return job_id


async def _run_job_in_session(
    job_id: str,
    *,
    session: AsyncSession,
    storage: StorageProvider,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    settings: Settings,
) -> None:
    job_repo = IngestionJobRepository(session)
    job = await job_repo.get(job_id)
    if job is None:
        raise RuntimeError(f"Missing ingestion job: {job_id}")

    doc_repo = DocumentRepository(session)
    document = await doc_repo.get(job.workspace_id, job.document_id)
    if document is None:
        raise RuntimeError(f"Missing document for ingestion job: {job_id}")
    if document.status == STATUS_DELETED:
        logger.info(
            "ingestion_job_skipped_deleted_document job_id=%s document_id=%s",
            job.id,
            document.id,
        )
        await job_repo.delete_by_document(document.id)
        await session.commit()
        return
    if not document.storage_path:
        raise RuntimeError(f"Document has no stored source content: {document.id}")
    logger.info(
        "ingestion_job_started job_id=%s document_id=%s attempt=%s",
        job.id,
        document.id,
        job.attempts,
    )

    raw_bytes = await storage.read(document.storage_path)
    chunk_repo = ChunkRepository(session)
    await chunk_repo.delete_by_document(document.id)
    vector_store.delete_by_document(document.id)

    result = await ingest_document(
        DocumentContext(
            document_id=document.id,
            workspace_id=document.workspace_id,
            title=document.title,
            source_type=document.source_type,
            external_document_id=document.external_document_id,
            citation_prefix=document.citation_prefix,
            country=document.country,
            country_code=document.country_code,
        ),
        text=_source_text(document.source_type, raw_bytes),
        pdf_bytes=raw_bytes if document.source_type == SOURCE_TYPE_PDF else None,
        docx_bytes=raw_bytes if document.source_type == SOURCE_TYPE_DOCX else None,
        language_hint=document.language if document.language != "unknown" else None,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        chunk_repo=chunk_repo,
        embedding_model_name=_embedding_model_label(settings),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    await session.refresh(document)
    if document.status == STATUS_DELETED:
        await chunk_repo.delete_by_document(document.id)
        vector_store.delete_by_document(document.id)
        await job_repo.delete_by_document(document.id)
        logger.info(
            "ingestion_job_discarded_deleted_document job_id=%s document_id=%s",
            job.id,
            document.id,
        )
        await session.commit()
        return

    await doc_repo.fill_missing_metadata(document, result.extracted_metadata)
    await doc_repo.update_status(
        document,
        status=STATUS_READY,
        chunk_count=result.chunk_count,
        embedding_model=_embedding_model_label(settings),
    )
    await job_repo.mark_succeeded(job)
    logger.info(
        "ingestion_job_succeeded job_id=%s document_id=%s chunk_count=%s",
        job.id,
        document.id,
        result.chunk_count,
    )
    await session.commit()


async def _handle_job_failure(
    job_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    vector_store: VectorStore,
    max_attempts: int,
    error_message: str,
) -> None:
    async with session_factory() as session:
        job_repo = IngestionJobRepository(session)
        job = await job_repo.get(job_id)
        if job is None:
            return
        should_retry = job.attempts < max_attempts

        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(job.workspace_id, job.document_id)
        if document is not None:
            if document.status == STATUS_DELETED:
                await ChunkRepository(session).delete_by_document(document.id)
                vector_store.delete_by_document(document.id)
                await job_repo.delete_by_document(document.id)
                await session.commit()
                return
            chunk_repo = ChunkRepository(session)
            await chunk_repo.delete_by_document(document.id)
            vector_store.delete_by_document(document.id)
            if should_retry:
                await doc_repo.update_status(
                    document,
                    status=STATUS_PROCESSING,
                    chunk_count=0,
                    error_message=None,
                )
            else:
                await doc_repo.update_status(
                    document,
                    status=STATUS_FAILED,
                    chunk_count=0,
                    error_message=error_message,
                )

        if should_retry:
            logger.warning(
                "ingestion_job_retrying job_id=%s document_id=%s attempt=%s max_attempts=%s",
                job.id,
                job.document_id,
                job.attempts,
                max_attempts,
            )
            await job_repo.mark_pending_for_retry(job, error_message=error_message)
        else:
            logger.error(
                "ingestion_job_failed_final job_id=%s document_id=%s attempts=%s",
                job.id,
                job.document_id,
                job.attempts,
            )
            await job_repo.mark_failed(job, error_message=error_message)
        await session.commit()


def _source_text(source_type: str, raw_bytes: bytes) -> str | None:
    if source_type in {SOURCE_TYPE_PDF, SOURCE_TYPE_DOCX}:
        return None
    return raw_bytes.decode("utf-8")


def _embedding_model_label(settings: Any) -> str:
    return "mock" if settings.embedding_provider == "mock" else settings.embedding_model
