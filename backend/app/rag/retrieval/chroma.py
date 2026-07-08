from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.rag.retrieval.lexical import (
    has_exact_keyword_or_table_match,
    score_lexical_candidates,
    tokenize_query_for_lexical,
)
from app.rag.retrieval.models import RetrievedChunk
from app.rag.retrieval.ranking import merge_candidates, select_final_chunks
from app.rag.retrieval.utils import optional_int, optional_str


class ChromaRetriever:
    def __init__(
        self,
        collection: Any,
        min_similarity: float = 0.75,
        final_context_count: int = 5,
        max_chunks_per_document: int = 3,
    ) -> None:
        self.min_similarity = min_similarity
        self.final_context_count = final_context_count
        self.max_chunks_per_document = max_chunks_per_document
        self._collection = collection

    async def retrieve(
        self,
        query: str,
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
        semantic_candidates = _filter_candidates(candidates, workspace_id, country, document_ids)
        lexical_candidates = self._lexical_candidates(
            query=query,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            candidate_count=candidate_count,
        )
        hybrid_candidates = merge_candidates(semantic_candidates, lexical_candidates)
        selected = select_final_chunks(
            hybrid_candidates,
            min_similarity=self.min_similarity,
            limit=self.final_context_count,
            max_chunks_per_document=self.max_chunks_per_document,
        )
        if selected:
            return selected

        # A high semantic threshold is useful for noise control, but it should
        # not suppress exact table-row/keyword evidence. When semantic scores
        # are too low, allow clearly matching lexical/table chunks through.
        exact_matches = [
            candidate
            for candidate in hybrid_candidates
            if has_exact_keyword_or_table_match(query, candidate)
        ]
        return select_final_chunks(
            exact_matches,
            min_similarity=min(self.min_similarity, 0.45),
            limit=self.final_context_count,
            max_chunks_per_document=self.max_chunks_per_document,
        )

    def _lexical_candidates(
        self,
        *,
        query: str,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        query_terms = tokenize_query_for_lexical(query)
        if not query_terms:
            return []

        where = _build_chroma_where(workspace_id=workspace_id, document_ids=document_ids)
        limit = max(candidate_count * 20, self.final_context_count * 10, 100)
        try:
            result = self._collection.get(
                where=where,
                include=["documents", "metadatas"],
                limit=limit,
            )
        except TypeError:
            result = self._collection.get(where=where, include=["documents", "metadatas"])

        candidates = _filter_candidates(
            _parse_chroma_get_result(result),
            workspace_id,
            country,
            document_ids,
        )
        return score_lexical_candidates(query_terms, candidates)


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
        chunks.append(_chunk_from_chroma_row(chunk_id, content, metadata, distance))
    return chunks


def _parse_chroma_get_result(result: dict[str, Any]) -> list[RetrievedChunk]:
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    chunks: list[RetrievedChunk] = []
    rows = zip(ids, documents, metadatas, strict=False)
    for chunk_id, content, metadata in rows:
        chunks.append(_chunk_from_chroma_row(chunk_id, content, metadata, None))
    return chunks


def _chunk_from_chroma_row(
    chunk_id: Any,
    content: Any,
    metadata: Any,
    distance: Any,
) -> RetrievedChunk:
    metadata = dict(metadata or {})
    raw_text = str(metadata.get("raw_text") or content or "")
    return RetrievedChunk(
        chunk_id=str(chunk_id),
        document_id=str(metadata.get("document_id") or ""),
        external_document_id=optional_str(metadata.get("external_document_id")),
        citation_prefix=optional_str(metadata.get("citation_prefix")),
        content=str(content or ""),
        raw_text=raw_text,
        title=str(metadata.get("title") or "Untitled document"),
        country=optional_str(metadata.get("country")),
        country_code=optional_str(metadata.get("country_code")),
        language=optional_str(metadata.get("language")),
        section_title=optional_str(metadata.get("section_title")),
        page_number=optional_int(metadata.get("page_number")),
        chunk_index=optional_int(metadata.get("chunk_index")),
        relevance_score=distance_to_similarity(distance),
        metadata=metadata,
    )


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
