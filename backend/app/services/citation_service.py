from __future__ import annotations

from pydantic import BaseModel

from app.rag.llm_providers import GroundedAnswer
from app.rag.retriever import LabeledChunk
from app.schemas.answers import AnswerSource


class CitationValidationResult(BaseModel):
    is_valid: bool
    cited_source_ids: list[str]
    invalid_source_ids: list[str]
    reason: str | None = None


def validate_citations(
    answer: GroundedAnswer,
    available_sources: list[LabeledChunk],
) -> CitationValidationResult:
    available_ids = {source.source_id for source in available_sources}
    cited = _unique_in_order(answer.source_ids)
    invalid = [source_id for source_id in cited if source_id not in available_ids]

    if invalid:
        return CitationValidationResult(
            is_valid=False,
            cited_source_ids=[source_id for source_id in cited if source_id in available_ids],
            invalid_source_ids=invalid,
            reason="Answer cited source labels that were not present in the prompt context.",
        )
    if answer.evidence_sufficient and not cited:
        return CitationValidationResult(
            is_valid=False,
            cited_source_ids=[],
            invalid_source_ids=[],
            reason="Answer marked evidence sufficient but did not cite any source.",
        )
    return CitationValidationResult(
        is_valid=True,
        cited_source_ids=cited,
        invalid_source_ids=[],
        reason=None,
    )


def source_cards_for_citations(
    available_sources: list[LabeledChunk],
    cited_source_ids: list[str],
) -> list[AnswerSource]:
    by_id = {source.source_id: source for source in available_sources}
    source_cards: list[AnswerSource] = []
    for source_id in cited_source_ids:
        labeled = by_id.get(source_id)
        if labeled is None:
            continue
        chunk = labeled.chunk
        source_cards.append(
            AnswerSource(
                chunk_id=chunk.chunk_id,
                source_id=source_id,
                document_id=chunk.document_id,
                external_document_id=chunk.external_document_id,
                document_title=chunk.title,
                country=chunk.country,
                language=chunk.language,
                section_title=chunk.section_title,
                page_number=chunk.page_number,
                snippet=chunk.raw_text,
                relevance_score=chunk.relevance_score,
            )
        )
    return source_cards


def _unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
