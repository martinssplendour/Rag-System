from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

import pytest

from app.rag.retrieval_cache import CachedRetrievalService, maybe_cache_retriever
from app.rag.retriever import RetrievedChunk


@pytest.mark.anyio
async def test_cached_retrieval_reuses_chunks_for_similar_question_embedding() -> None:
    retriever = FakeRetriever()
    cached = _cached(retriever)

    first = await cached.retrieve([1.0, 0.0], "workspace-a", "Germany", None, 12)
    second = await cached.retrieve([0.999, 0.001], "workspace-a", "Germany", None, 12)

    assert retriever.calls == 1
    assert [chunk.chunk_id for chunk in first] == ["chunk-1"]
    assert [chunk.chunk_id for chunk in second] == ["chunk-1"]


@pytest.mark.anyio
async def test_cached_retrieval_is_scoped_by_workspace() -> None:
    retriever = FakeRetriever()
    cached = _cached(retriever)

    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)
    await cached.retrieve([1.0, 0.0], "workspace-b", None, None, 12)

    assert retriever.calls == 2


@pytest.mark.anyio
async def test_cached_retrieval_is_scoped_by_filters() -> None:
    retriever = FakeRetriever()
    cached = _cached(retriever)

    await cached.retrieve([1.0, 0.0], "workspace-a", "Germany", None, 12)
    await cached.retrieve([1.0, 0.0], "workspace-a", "France", None, 12)
    await cached.retrieve([1.0, 0.0], "workspace-a", "Germany", ["doc-1"], 12)

    assert retriever.calls == 3


@pytest.mark.anyio
async def test_cached_retrieval_expires_entries() -> None:
    retriever = FakeRetriever()
    cached = _cached(retriever, ttl_seconds=0.01)

    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)
    await asyncio.sleep(0.02)
    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)

    assert retriever.calls == 2


@pytest.mark.anyio
async def test_cached_retrieval_misses_when_question_embedding_is_not_similar_enough() -> None:
    retriever = FakeRetriever()
    cached = _cached(retriever, similarity_threshold=0.99)

    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)
    await cached.retrieve([0.0, 1.0], "workspace-a", None, None, 12)

    assert retriever.calls == 2


@pytest.mark.anyio
async def test_cached_retrieval_invalidates_when_collection_version_changes() -> None:
    retriever = FakeRetriever()
    collection_version = "v1"
    cached = _cached(retriever, collection_version_getter=lambda: collection_version)

    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)
    collection_version = "v2"
    await cached.retrieve([1.0, 0.0], "workspace-a", None, None, 12)

    assert retriever.calls == 2


def test_maybe_cache_retriever_can_be_disabled() -> None:
    retriever = FakeRetriever()

    wrapped = maybe_cache_retriever(
        retriever,
        enabled=False,
        ttl_seconds=60,
        max_question_entries=10,
        max_chunk_entries=10,
        similarity_threshold=0.97,
    )

    assert wrapped is retriever


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(
        self,
        query_embedding: Sequence[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        del query_embedding, country, document_ids, candidate_count
        self.calls += 1
        return [_chunk(chunk_id=f"chunk-{self.calls}", workspace_id=workspace_id)]


def _cached(
    retriever: FakeRetriever,
    *,
    ttl_seconds: float = 60,
    similarity_threshold: float = 0.97,
    collection_version_getter: Callable[[], str] | None = None,
) -> CachedRetrievalService:
    return CachedRetrievalService(
        retriever,
        ttl_seconds=ttl_seconds,
        max_question_entries=10,
        max_chunk_entries=10,
        similarity_threshold=similarity_threshold,
        collection_version_getter=collection_version_getter or (lambda: "v1"),
    )


def _chunk(chunk_id: str, workspace_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc-a",
        content=f"Evidence for {chunk_id}",
        raw_text=f"Evidence for {chunk_id}",
        title="Evidence document",
        relevance_score=0.80,
        metadata={"workspace_id": workspace_id, "status": "ready"},
    )
