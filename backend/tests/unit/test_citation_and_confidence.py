from __future__ import annotations

from app.rag.llm_providers import GroundedAnswer
from app.rag.retriever import LabeledChunk, RetrievedChunk
from app.schemas.answers import AnswerSource
from app.services.citation_service import source_cards_for_citations, validate_citations
from app.services.confidence_service import calculate_confidence


def test_validate_citations_rejects_unknown_source_ids() -> None:
    answer = GroundedAnswer(
        answer="Answer [UK-NICE-001][UK-NICE-999]",
        source_ids=["UK-NICE-001", "UK-NICE-999"],
        evidence_sufficient=True,
    )

    result = validate_citations(answer, [_labeled("UK-NICE-001", "chunk-1")])

    assert not result.is_valid
    assert result.cited_source_ids == ["UK-NICE-001"]
    assert result.invalid_source_ids == ["UK-NICE-999"]


def test_validate_citations_requires_citation_when_evidence_sufficient() -> None:
    answer = GroundedAnswer(
        answer="Uncited answer",
        source_ids=[],
        evidence_sufficient=True,
    )

    result = validate_citations(answer, [_labeled("UK-NICE-001", "chunk-1")])

    assert not result.is_valid


def test_source_cards_use_raw_text_for_snippets() -> None:
    labeled = _labeled(
        "UK-NICE-001",
        "chunk-1",
        content="semantic block",
        raw_text="literal source",
    )

    cards = source_cards_for_citations([labeled], ["UK-NICE-001"])

    assert cards[0].snippet == "literal source"
    assert cards[0].snippet != "semantic block"
    assert cards[0].chunk_id == "chunk-1"


def test_confidence_tiers() -> None:
    strong_sources = [
        _source("UK-NICE-001", "chunk-1", "doc-a", 0.81),
        _source("UK-NICE-002", "chunk-2", "doc-a", 0.78),
    ]
    medium_sources = [_source("UK-NICE-001", "chunk-1", "doc-a", 0.50)]

    assert (
        calculate_confidence(
            evidence_sufficient=True,
            citation_validation_passed=True,
            cited_sources=strong_sources,
            min_similarity=0.45,
            high_similarity=0.75,
        )
        == "high"
    )
    assert (
        calculate_confidence(
            evidence_sufficient=True,
            citation_validation_passed=True,
            cited_sources=medium_sources,
            min_similarity=0.45,
            high_similarity=0.75,
        )
        == "medium"
    )
    assert (
        calculate_confidence(
            evidence_sufficient=False,
            citation_validation_passed=True,
            cited_sources=strong_sources,
            min_similarity=0.45,
            high_similarity=0.75,
        )
        == "low"
    )


def _labeled(
    source_id: str,
    chunk_id: str,
    content: str = "content",
    raw_text: str = "raw",
) -> LabeledChunk:
    return LabeledChunk(
        source_id=source_id,
        chunk=RetrievedChunk(
            chunk_id=chunk_id,
            document_id="doc-a",
            external_document_id="external-doc",
            content=content,
            raw_text=raw_text,
            title="Document",
            country="United Kingdom",
            language="en",
            relevance_score=0.8,
            metadata={"workspace_id": "workspace", "status": "ready"},
        ),
    )


def _source(
    source_id: str,
    chunk_id: str,
    document_id: str,
    relevance_score: float,
) -> AnswerSource:
    return AnswerSource(
        chunk_id=chunk_id,
        source_id=source_id,
        document_id=document_id,
        document_title="Document",
        snippet="literal source",
        relevance_score=relevance_score,
    )
