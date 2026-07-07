from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import AppError
from app.core.constants import STATUS_DELETED
from app.repositories.answers import PostgresAnswerRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_jobs import IngestionJobRepository
from app.storage.base import StorageProvider
from app.utils.hashing import sha256_hex
from app.vectorstores.base import VectorStore

logger = logging.getLogger("market_access_evidence_assistant")


@dataclass(frozen=True)
class DeletedDocumentCleanup:
    workspace_id: str
    document_id: str
    storage_path: str | None


async def soft_delete_document(
    *,
    session: AsyncSession,
    workspace_id: str,
    document_id: str,
) -> DeletedDocumentCleanup:
    document = await DocumentRepository(session).get(workspace_id, document_id)
    if document is None:
        raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)

    storage_path = document.storage_path
    if document.status != STATUS_DELETED:
        document.status = STATUS_DELETED
        document.chunk_count = 0
        document.error_message = None
        document.content_hash = _deleted_content_hash(document.id, document.content_hash)
        await session.flush()
        await session.commit()
        logger.info(
            "document_soft_deleted workspace_id=%s document_id=%s",
            workspace_id,
            document_id,
        )

    return DeletedDocumentCleanup(
        workspace_id=workspace_id,
        document_id=document_id,
        storage_path=storage_path,
    )


async def cleanup_deleted_document(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageProvider,
    vector_store: VectorStore,
    retriever: object,
    workspace_id: str,
    document_id: str,
    storage_path: str | None,
) -> None:
    try:
        vector_store.delete_by_document(document_id)
    except Exception:
        logger.exception("document_vector_cleanup_failed document_id=%s", document_id)

    try:
        async with session_factory() as session:
            await PostgresAnswerRepository(session).delete_sources_by_document(workspace_id, document_id)
            await ChunkRepository(session).delete_by_document(document_id)
            await IngestionJobRepository(session).delete_by_document(document_id)

            document = await DocumentRepository(session).get(workspace_id, document_id)
            if document is not None:
                document.chunk_count = 0
                if storage_path:
                    document.storage_path = None
            await session.commit()
    except Exception:
        logger.exception("document_database_cleanup_failed document_id=%s", document_id)

    if storage_path:
        try:
            await storage.delete(storage_path)
        except Exception:
            logger.exception("document_storage_cleanup_failed document_id=%s", document_id)

    try:
        await _clear_retrieval_cache(retriever)
    except Exception:
        logger.exception("document_cache_cleanup_failed document_id=%s", document_id)

    logger.info("document_cleanup_finished document_id=%s", document_id)


async def _clear_retrieval_cache(retriever: object) -> None:
    clear = getattr(retriever, "clear", None)
    if clear is None:
        return
    result = clear()
    if inspect.isawaitable(result):
        await result


def _deleted_content_hash(document_id: str, content_hash: str) -> str:
    return sha256_hex(f"deleted:{document_id}:{content_hash}".encode())
