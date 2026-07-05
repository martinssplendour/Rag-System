"""Persistence for the ``documents`` table.

Owns queries only -- no business rules (see modularity checklist, layer
boundaries). Field-merge precedence rules live in the service layer, not
here; this repository just applies whatever values it is given.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Document

_MERGEABLE_FIELDS = (
    "external_document_id",
    "country",
    "country_code",
    "language",
    "therapy_area",
    "technology_type",
    "assessment_body",
)


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, workspace_id: str, content_hash: str) -> Document | None:
        stmt = select(Document).where(
            Document.workspace_id == workspace_id, Document.content_hash == content_hash
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        return document

    async def update_status(
        self,
        document: Document,
        *,
        status: str,
        chunk_count: int | None = None,
        embedding_model: str | None = None,
        error_message: str | None = None,
    ) -> None:
        document.status = status
        document.error_message = error_message
        if chunk_count is not None:
            document.chunk_count = chunk_count
        if embedding_model is not None:
            document.embedding_model = embedding_model
        await self._session.flush()

    async def fill_missing_metadata(self, document: Document, extracted: dict[str, str]) -> None:
        """Fill fields the caller left unset using header-extracted values.

        Explicit values supplied at upload time always win -- this only
        touches fields that are still None/empty/"unknown".
        """
        for field in _MERGEABLE_FIELDS:
            current = getattr(document, field, None)
            candidate = extracted.get(field)
            if candidate and current in (None, "", "unknown"):
                setattr(document, field, candidate)
        await self._session.flush()

    async def list_all(self, workspace_id: str) -> list[Document]:
        stmt = select(Document).where(Document.workspace_id == workspace_id).order_by(Document.created_at)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, workspace_id: str, document_id: str) -> Document | None:
        stmt = select(Document).where(Document.workspace_id == workspace_id, Document.id == document_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()
