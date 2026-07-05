"""Chroma-backed vector store for the local MVP.

Embeddings are always computed up front by the configured EmbeddingProvider
and passed in explicitly -- Chroma's own embedding-function machinery is
not used, so there is exactly one embedding code path in the app (shared
with query-time embedding in Part 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

COLLECTION_NAME = "market_access_chunks"


@dataclass(frozen=True)
class ChromaResources:
    client: Any
    collection: Any


def build_chroma_resources(
    persist_dir: str | Path,
    collection_name: str = COLLECTION_NAME,
) -> ChromaResources:
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return ChromaResources(client=client, collection=collection)


class ChromaVectorStore:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """``chunks``: list of {id, embedding, document_text, metadata}."""
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk["id"] for chunk in chunks],
            embeddings=[chunk["embedding"] for chunk in chunks],
            documents=[chunk["document_text"] for chunk in chunks],
            metadatas=[chunk["metadata"] for chunk in chunks],
        )

    def delete_by_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._collection.count()
