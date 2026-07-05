from __future__ import annotations

from app.rag.retriever import (
    RetrievedChunk,
    assign_source_labels,
    distance_to_similarity,
    select_final_chunks,
)


def test_select_final_chunks_filters_threshold_and_caps_per_document() -> None:
    chunks = [
        _chunk("1", "doc-a", 0.91, "alpha evidence"),
        _chunk("2", "doc-a", 0.90, "beta evidence"),
        _chunk("3", "doc-a", 0.89, "gamma evidence"),
        _chunk("4", "doc-b", 0.88, "delta evidence"),
        _chunk("5", "doc-c", 0.30, "weak evidence"),
    ]

    selected = select_final_chunks(
        chunks,
        min_similarity=0.45,
        limit=4,
        max_chunks_per_document=2,
    )

    assert [chunk.chunk_id for chunk in selected] == ["1", "2", "4"]


def test_select_final_chunks_removes_near_duplicate_text() -> None:
    chunks = [
        _chunk("1", "doc-a", 0.91, "same evidence text"),
        _chunk("2", "doc-b", 0.90, "same evidence text"),
        _chunk("3", "doc-c", 0.89, "different evidence text"),
    ]

    selected = select_final_chunks(
        chunks,
        min_similarity=0.45,
        limit=5,
        max_chunks_per_document=3,
    )

    assert [chunk.chunk_id for chunk in selected] == ["1", "3"]


def test_assign_source_labels_is_stable_and_request_local() -> None:
    chunks = [
        _chunk("abc", "doc-a", 0.80, "first"),
        _chunk("def", "doc-b", 0.79, "second"),
    ]

    labeled = assign_source_labels(chunks)

    assert [(source.source_id, source.chunk.chunk_id) for source in labeled] == [
        ("S1", "abc"),
        ("S2", "def"),
    ]


def test_distance_to_similarity_is_bounded() -> None:
    assert distance_to_similarity(0.2) == 0.8
    assert distance_to_similarity(-1.0) == 1.0
    assert distance_to_similarity(2.0) == 0.0
    assert distance_to_similarity(None) == 0.0


def _chunk(
    chunk_id: str,
    document_id: str,
    relevance_score: float,
    raw_text: str,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=raw_text,
        raw_text=raw_text,
        title="Doc",
        relevance_score=relevance_score,
        metadata={"workspace_id": "workspace", "status": "ready"},
    )
