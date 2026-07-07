from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.rag.retriever import RetrievalService, RetrievedChunk


@dataclass(frozen=True)
class RetrievalCacheSnapshot:
    question_hits: int
    question_misses: int
    chunk_hits: int
    chunk_misses: int
    stores: int


@dataclass(frozen=True)
class _QuestionCacheEntry:
    expires_at: float
    scope_key: str
    query_embedding: tuple[float, ...]
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ChunkCacheEntry:
    expires_at: float
    chunk: RetrievedChunk


class CachedRetrievalService:
    """Tenant-scoped retrieval cache with a hot chunk payload cache.

    The question cache stores embeddings and chunk IDs, not raw questions or
    final answers. The chunk cache stores the selected chunk payloads that are
    safe to reuse when the tenant, filters, and collection version match.
    """

    def __init__(
        self,
        retriever: RetrievalService,
        *,
        ttl_seconds: float,
        max_question_entries: int,
        max_chunk_entries: int,
        similarity_threshold: float,
        collection_version_getter: Callable[[], str] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_question_entries <= 0:
            raise ValueError("max_question_entries must be positive")
        if max_chunk_entries <= 0:
            raise ValueError("max_chunk_entries must be positive")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0.0 and 1.0")

        self._retriever = retriever
        self._collection = getattr(retriever, "_collection", None)
        self._ttl_seconds = ttl_seconds
        self._max_question_entries = max_question_entries
        self._max_chunk_entries = max_chunk_entries
        self._similarity_threshold = similarity_threshold
        self._collection_version_getter = collection_version_getter or (lambda: "static")

        self._question_cache: OrderedDict[str, _QuestionCacheEntry] = OrderedDict()
        self._chunk_cache: OrderedDict[str, _ChunkCacheEntry] = OrderedDict()
        self._next_question_entry_id = 0
        self._lock = asyncio.Lock()
        self._question_hits = 0
        self._question_misses = 0
        self._chunk_hits = 0
        self._chunk_misses = 0
        self._stores = 0

    async def retrieve(
        self,
        query_embedding: Sequence[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        collection_version = self._collection_version_getter()
        scope_key = _scope_key(
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            candidate_count=candidate_count,
            collection_version=collection_version,
        )
        query_vector = tuple(float(value) for value in query_embedding)

        cached_chunk_ids = await self._find_question_entry(scope_key, query_vector)
        if cached_chunk_ids is not None:
            cached_chunks = await self._get_chunks(
                workspace_id=workspace_id,
                collection_version=collection_version,
                chunk_ids=cached_chunk_ids,
            )
            if cached_chunks is not None:
                return cached_chunks

        chunks = await self._retriever.retrieve(
            query_embedding=query_embedding,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            candidate_count=candidate_count,
        )
        if chunks:
            await self._store(
                scope_key=scope_key,
                workspace_id=workspace_id,
                collection_version=collection_version,
                query_embedding=query_vector,
                chunks=chunks,
            )
        return chunks

    async def snapshot(self) -> RetrievalCacheSnapshot:
        async with self._lock:
            return RetrievalCacheSnapshot(
                question_hits=self._question_hits,
                question_misses=self._question_misses,
                chunk_hits=self._chunk_hits,
                chunk_misses=self._chunk_misses,
                stores=self._stores,
            )

    async def clear(self) -> None:
        async with self._lock:
            self._question_cache.clear()
            self._chunk_cache.clear()

    async def _find_question_entry(
        self,
        scope_key: str,
        query_embedding: tuple[float, ...],
    ) -> tuple[str, ...] | None:
        now = time.monotonic()
        best_key: str | None = None
        best_entry: _QuestionCacheEntry | None = None
        best_similarity = -1.0

        async with self._lock:
            self._remove_expired_question_entries(now)
            for entry_key, entry in self._question_cache.items():
                if entry.scope_key != scope_key:
                    continue
                similarity = _cosine_similarity(query_embedding, entry.query_embedding)
                if similarity > best_similarity:
                    best_key = entry_key
                    best_entry = entry
                    best_similarity = similarity

            if best_entry is None or best_similarity < self._similarity_threshold:
                self._question_misses += 1
                return None

            self._question_cache.move_to_end(best_key)
            self._question_hits += 1
            return best_entry.chunk_ids

    async def _get_chunks(
        self,
        *,
        workspace_id: str,
        collection_version: str,
        chunk_ids: tuple[str, ...],
    ) -> list[RetrievedChunk] | None:
        now = time.monotonic()
        chunks: list[RetrievedChunk] = []

        async with self._lock:
            self._remove_expired_chunk_entries(now)
            for chunk_id in chunk_ids:
                cache_key = _chunk_cache_key(
                    workspace_id=workspace_id,
                    collection_version=collection_version,
                    chunk_id=chunk_id,
                )
                entry = self._chunk_cache.get(cache_key)
                if entry is None:
                    self._chunk_misses += 1
                    return None
                self._chunk_cache.move_to_end(cache_key)
                chunks.append(entry.chunk.model_copy(deep=True))

            self._chunk_hits += len(chunks)
            return chunks

    async def _store(
        self,
        *,
        scope_key: str,
        workspace_id: str,
        collection_version: str,
        query_embedding: tuple[float, ...],
        chunks: list[RetrievedChunk],
    ) -> None:
        now = time.monotonic()
        expires_at = now + self._ttl_seconds
        chunk_ids = tuple(chunk.chunk_id for chunk in chunks)

        async with self._lock:
            self._remove_expired_question_entries(now)
            self._remove_expired_chunk_entries(now)

            for chunk in chunks:
                cache_key = _chunk_cache_key(
                    workspace_id=workspace_id,
                    collection_version=collection_version,
                    chunk_id=chunk.chunk_id,
                )
                self._chunk_cache[cache_key] = _ChunkCacheEntry(
                    expires_at=expires_at,
                    chunk=chunk.model_copy(deep=True),
                )
                self._chunk_cache.move_to_end(cache_key)

            entry_key = f"question:{self._next_question_entry_id}"
            self._next_question_entry_id += 1
            self._question_cache[entry_key] = _QuestionCacheEntry(
                expires_at=expires_at,
                scope_key=scope_key,
                query_embedding=query_embedding,
                chunk_ids=chunk_ids,
            )
            self._question_cache.move_to_end(entry_key)

            while len(self._question_cache) > self._max_question_entries:
                self._question_cache.popitem(last=False)
            while len(self._chunk_cache) > self._max_chunk_entries:
                self._chunk_cache.popitem(last=False)

            self._stores += 1

    def _remove_expired_question_entries(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._question_cache.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._question_cache[key]

    def _remove_expired_chunk_entries(self, now: float) -> None:
        expired_keys = [key for key, entry in self._chunk_cache.items() if entry.expires_at <= now]
        for key in expired_keys:
            del self._chunk_cache[key]


def maybe_cache_retriever(
    retriever: RetrievalService,
    *,
    enabled: bool,
    ttl_seconds: float,
    max_question_entries: int,
    max_chunk_entries: int,
    similarity_threshold: float,
    collection_version_getter: Callable[[], str] | None = None,
) -> RetrievalService:
    if not enabled:
        return retriever
    return CachedRetrievalService(
        retriever,
        ttl_seconds=ttl_seconds,
        max_question_entries=max_question_entries,
        max_chunk_entries=max_chunk_entries,
        similarity_threshold=similarity_threshold,
        collection_version_getter=collection_version_getter,
    )


def _scope_key(
    *,
    workspace_id: str,
    country: str | None,
    document_ids: list[str] | None,
    candidate_count: int,
    collection_version: str,
) -> str:
    payload = {
        "workspace_id": workspace_id,
        "country": (country or "").strip().lower(),
        "document_ids": sorted(document_ids or []),
        "candidate_count": candidate_count,
        "collection_version": collection_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _chunk_cache_key(*, workspace_id: str, collection_version: str, chunk_id: str) -> str:
    payload = f"{workspace_id}\0{collection_version}\0{chunk_id}".encode()
    return hashlib.sha256(payload).hexdigest()


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot_product = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        dot_product += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (math.sqrt(left_norm) * math.sqrt(right_norm))
