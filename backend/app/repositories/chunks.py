"""Persistence for the ``document_chunks`` table."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import DocumentChunk


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, chunks: list[DocumentChunk]) -> None:
        self._session.add_all(chunks)
        await self._session.flush()

    async def delete_by_document(self, document_id: str) -> None:
        await self._session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        await self._session.flush()

    async def list_by_document(self, document_id: str) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list((await self._session.execute(stmt)).scalars().all())
