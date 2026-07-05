"""Request/response models for the /documents endpoints.

DocumentResponse renames the ORM's ``id`` to ``document_id`` for the public
API, so mapping is done through an explicit function rather than
``model_validate(..., from_attributes=True)`` -- that only matches
identically-named attributes and would silently 500 on a rename like this
(caught live via a smoke test against the real dataset).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.repositories.models import Document

DocumentStatus = Literal["processing", "ready", "failed"]


class DocumentResponse(BaseModel):
    document_id: str
    external_document_id: str | None
    title: str
    filename: str | None
    country: str | None
    language: str
    status: DocumentStatus
    chunk_count: int
    created_at: datetime


class DocumentListItem(DocumentResponse):
    technology_type: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int


def _base_fields(document: Document) -> dict:
    return {
        "document_id": document.id,
        "external_document_id": document.external_document_id,
        "title": document.title,
        "filename": document.filename,
        "country": document.country,
        "language": document.language,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at,
    }


def to_document_response(document: Document) -> DocumentResponse:
    return DocumentResponse(**_base_fields(document))


def to_document_list_item(document: Document) -> DocumentListItem:
    return DocumentListItem(**_base_fields(document), technology_type=document.technology_type)
