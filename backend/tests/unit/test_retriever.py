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


def test_assign_source_labels_are_globally_stable() -> None:
    chunks = [
        _chunk(
            "abc",
            "doc-a",
            0.80,
            "first",
            external_document_id="uk_nice_oncology_drug_summary",
            country="United Kingdom",
            country_code="UK",
            chunk_index=0,
        ),
        _chunk(
            "def",
            "doc-b",
            0.79,
            "second",
            external_document_id="france_has_medtech_reimbursement_summary",
            country="France",
            country_code="FR",
            chunk_index=2,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [(source.source_id, source.chunk.chunk_id) for source in labeled] == [
        ("UK-NICE-001", "abc"),
        ("FR-HAS-003", "def"),
    ]


def test_assign_source_labels_uses_document_code_priorities() -> None:
    chunks = [
        _chunk(
            "de",
            "doc-de",
            0.80,
            "first",
            external_document_id="germany_amnog_digital_therapeutic_note_de",
            country="Deutschland",
            chunk_index=12,
        ),
        _chunk(
            "it",
            "doc-it",
            0.79,
            "second",
            external_document_id="italy_pricing_reimbursement_pathway_note",
            country="Italy",
            chunk_index=0,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [source.source_id for source in labeled] == [
        "DE-AMNOG-013",
        "IT-PRICING-001",
    ]


def test_assign_source_labels_prefers_stored_citation_prefix() -> None:
    chunks = [
        _chunk(
            "abc",
            "doc-a",
            0.80,
            "first",
            external_document_id="uk_nice_oncology_drug_summary",
            citation_prefix="UK-NICE",
            country="United Kingdom",
            chunk_index=0,
        ),
        _chunk(
            "def",
            "doc-b",
            0.79,
            "second",
            external_document_id="uk_nice_second_oncology_summary",
            citation_prefix="UK-NICE-02",
            country="United Kingdom",
            chunk_index=0,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [source.source_id for source in labeled] == [
        "UK-NICE-001",
        "UK-NICE-02-001",
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
    external_document_id: str | None = None,
    citation_prefix: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    chunk_index: int | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        external_document_id=external_document_id,
        citation_prefix=citation_prefix,
        content=raw_text,
        raw_text=raw_text,
        title="Doc",
        country=country,
        country_code=country_code,
        chunk_index=chunk_index,
        relevance_score=relevance_score,
        metadata={"workspace_id": "workspace", "status": "ready"},
    )
