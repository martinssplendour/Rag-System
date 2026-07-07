from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.rag.citation_labels import (
    build_chunk_source_id,
    build_document_citation_base,
)


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
        query_embedding: Sequence[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]: ...


class ChromaRetriever:
    def __init__(
        self,
        collection: Any,
        min_similarity: float = 0.45,
        final_context_count: int = 5,
        max_chunks_per_document: int = 3,
    ) -> None:
        self.min_similarity = min_similarity
        self.final_context_count = final_context_count
        self.max_chunks_per_document = max_chunks_per_document
        self._collection = collection

    async def retrieve(
        self,
        query_embedding: Sequence[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        where = _build_chroma_where(workspace_id=workspace_id, document_ids=document_ids)
        n_results = max(candidate_count * 4, self.final_context_count)
        result = self._collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        candidates = _parse_chroma_query_result(result)
        filtered = _filter_candidates(candidates, workspace_id, country, document_ids)
        return select_final_chunks(
            filtered,
            min_similarity=self.min_similarity,
            limit=self.final_context_count,
            max_chunks_per_document=self.max_chunks_per_document,
        )


def select_final_chunks(
    candidates: Sequence[RetrievedChunk],
    min_similarity: float,
    limit: int,
    max_chunks_per_document: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    per_document_count: dict[str, int] = defaultdict(int)

    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: candidate.relevance_score,
        reverse=True,
    )

    for candidate in sorted_candidates:
        if candidate.relevance_score < min_similarity:
            continue
        if candidate.chunk_id in seen_chunk_ids:
            continue
        if per_document_count[candidate.document_id] >= max_chunks_per_document:
            continue
        if _is_near_duplicate(candidate, selected):
            continue

        selected.append(candidate)
        seen_chunk_ids.add(candidate.chunk_id)
        per_document_count[candidate.document_id] += 1

        if len(selected) >= limit:
            break

    return selected


def assign_source_labels(chunks: Sequence[RetrievedChunk]) -> list[LabeledChunk]:
    return [
        LabeledChunk(source_id=_stable_source_id(chunk), chunk=chunk)
        for chunk in chunks
    ]


def _stable_source_id(chunk: RetrievedChunk) -> str:
    prefix = chunk.citation_prefix or _optional_str(chunk.metadata.get("citation_prefix"))
    if not prefix:
        prefix = build_document_citation_base(
            country=chunk.country or _optional_str(chunk.metadata.get("country")),
            country_code=chunk.country_code or _optional_str(chunk.metadata.get("country_code")),
            document_identity=" ".join(
                value
                for value in [
                    chunk.external_document_id,
                    _optional_str(chunk.metadata.get("external_document_id")),
                    chunk.title,
                    chunk.document_id,
                ]
                if value
            ),
        )
    chunk_index = chunk.chunk_index
    if chunk_index is None:
        chunk_index = _optional_int(chunk.metadata.get("chunk_index"))
    return build_chunk_source_id(
        citation_prefix=prefix,
        chunk_index=chunk_index,
        chunk_id=chunk.chunk_id,
    )


def distance_to_similarity(distance: float | int | None) -> float:
    if distance is None:
        return 0.0
    # Chroma returns distances where lower is better. For cosine distance this maps
    # cleanly to a 0..1 support score; for other metrics it remains deterministic.
    return max(0.0, min(1.0, 1.0 - float(distance)))


def _build_chroma_where(
    workspace_id: str,
    document_ids: list[str] | None,
) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {"workspace_id": workspace_id},
        {"status": "ready"},
    ]
    if document_ids:
        filters.append({"document_id": {"$in": document_ids}})
    return filters[0] if len(filters) == 1 else {"$and": filters}


def _parse_chroma_query_result(result: dict[str, Any]) -> list[RetrievedChunk]:
    ids = _first_result_list(result.get("ids"))
    documents = _first_result_list(result.get("documents"))
    metadatas = _first_result_list(result.get("metadatas"))
    distances = _first_result_list(result.get("distances"))

    chunks: list[RetrievedChunk] = []
    rows = zip(ids, documents, metadatas, distances, strict=False)
    for chunk_id, content, metadata, distance in rows:
        metadata = dict(metadata or {})
        raw_text = str(metadata.get("raw_text") or content or "")
        chunks.append(
            RetrievedChunk(
                chunk_id=str(chunk_id),
                document_id=str(metadata.get("document_id") or ""),
                external_document_id=_optional_str(metadata.get("external_document_id")),
                citation_prefix=_optional_str(metadata.get("citation_prefix")),
                content=str(content or ""),
                raw_text=raw_text,
                title=str(metadata.get("title") or "Untitled document"),
                country=_optional_str(metadata.get("country")),
                country_code=_optional_str(metadata.get("country_code")),
                language=_optional_str(metadata.get("language")),
                section_title=_optional_str(metadata.get("section_title")),
                page_number=_optional_int(metadata.get("page_number")),
                chunk_index=_optional_int(metadata.get("chunk_index")),
                relevance_score=distance_to_similarity(distance),
                metadata=metadata,
            )
        )
    return chunks


def _filter_candidates(
    candidates: Sequence[RetrievedChunk],
    workspace_id: str,
    country: str | None,
    document_ids: list[str] | None,
) -> list[RetrievedChunk]:
    requested_country = country.lower() if country else None
    requested_documents = set(document_ids or [])
    filtered: list[RetrievedChunk] = []

    for candidate in candidates:
        if str(candidate.metadata.get("workspace_id")) != workspace_id:
            continue
        if candidate.metadata.get("status") != "ready":
            continue
        if requested_documents and candidate.document_id not in requested_documents:
            continue
        if requested_country:
            country_values = {
                (candidate.country or "").lower(),
                (candidate.country_code or "").lower(),
            }
            if requested_country not in country_values:
                continue
        if not candidate.content.strip() and not candidate.raw_text.strip():
            continue
        filtered.append(candidate)

    return filtered


def _first_result_list(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    if isinstance(value, list):
        return value
    return []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_near_duplicate(candidate: RetrievedChunk, selected: Sequence[RetrievedChunk]) -> bool:
    candidate_text = _normalise_for_similarity(candidate.raw_text or candidate.content)
    if not candidate_text:
        return False
    for existing in selected:
        existing_text = _normalise_for_similarity(existing.raw_text or existing.content)
        if candidate_text == existing_text:
            return True
        if SequenceMatcher(None, candidate_text, existing_text).ratio() >= 0.95:
            return True
    return False


def _normalise_for_similarity(value: str) -> str:
    return " ".join(value.lower().split())
