from __future__ import annotations

from collections.abc import Sequence

from app.schemas.answers import AnswerSource, Confidence


def calculate_confidence(
    *,
    evidence_sufficient: bool,
    citation_validation_passed: bool,
    cited_sources: Sequence[AnswerSource],
    min_similarity: float,
    high_similarity: float,
    conflict_detected: bool = False,
) -> Confidence:
    if not evidence_sufficient or not citation_validation_passed or conflict_detected:
        return "low"
    if not cited_sources:
        return "low"

    top_similarity = max(source.relevance_score for source in cited_sources)
    strong_sources = [
        source for source in cited_sources if source.relevance_score >= high_similarity
    ]
    unique_documents = {source.document_id for source in cited_sources}

    if (
        len(strong_sources) >= 2
        and len(unique_documents) >= 1
        and top_similarity >= high_similarity
    ):
        return "high"
    if top_similarity >= min_similarity:
        return "medium"
    return "low"
