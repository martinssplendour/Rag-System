from __future__ import annotations

from app.rag.citation_labels import (
    allocate_document_citation_prefix,
    build_chunk_source_id,
    build_document_citation_base,
)


def test_document_citation_base_is_readable_and_stable() -> None:
    assert (
        build_document_citation_base(
            country="United Kingdom",
            country_code="UK",
            document_identity="uk_nice_oncology_drug_summary",
        )
        == "UK-NICE"
    )


def test_document_citation_prefix_allocation_avoids_reuse() -> None:
    existing = {"UK-NICE", "UK-NICE-02"}

    assert allocate_document_citation_prefix("UK-NICE", existing) == "UK-NICE-03"


def test_chunk_source_id_uses_document_prefix_and_chunk_number() -> None:
    assert (
        build_chunk_source_id(
            citation_prefix="UK-NICE-02",
            chunk_index=0,
            chunk_id="chunk-id",
        )
        == "UK-NICE-02-001"
    )
