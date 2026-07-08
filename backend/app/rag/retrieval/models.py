from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    external_document_id: str | None = None
    citation_prefix: str | None = None
    content: str
    raw_text: str
    title: str
    country: str | None = None
    country_code: str | None = None
    language: str | None = None
    section_title: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    relevance_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LabeledChunk(BaseModel):
    source_id: str
    chunk: RetrievedChunk


class RetrievalService(Protocol):
    async def retrieve(
        self,
        query: str,
        query_embedding: Sequence[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]: ...
