"""Compatibility exports for retrieval components.

The implementation lives under ``app.rag.retrieval`` so each file owns one
retrieval concern: models, Chroma access, ranking, lexical scoring, and
source labeling. Existing imports from ``app.rag.retriever`` remain stable.
"""

from __future__ import annotations

from app.rag.retrieval.chroma import ChromaRetriever, distance_to_similarity
from app.rag.retrieval.models import LabeledChunk, RetrievalService, RetrievedChunk
from app.rag.retrieval.ranking import select_final_chunks
from app.rag.retrieval.source_labels import assign_source_labels

__all__ = [
    "ChromaRetriever",
    "LabeledChunk",
    "RetrievalService",
    "RetrievedChunk",
    "assign_source_labels",
    "distance_to_similarity",
    "select_final_chunks",
]
