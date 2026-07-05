from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

STANDARD_LIMITATION = (
    "This response is based only on the uploaded market-access documents and is "
    "not medical, legal, regulatory, reimbursement, or pricing advice."
)
INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find sufficient evidence in the available documents to answer this question."
)
INSUFFICIENT_EVIDENCE_UNCERTAINTY = (
    "No sufficiently relevant source passages were retrieved."
)

Confidence = Literal["high", "medium", "low"]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    country: str | None = Field(default=None, max_length=80)
    document_ids: list[str] | None = None

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be blank.")
        return stripped

    @field_validator("country")
    @classmethod
    def strip_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalised = [item.strip() for item in value if item and item.strip()]
        if len(normalised) != len(value):
            raise ValueError("document_ids must not contain blank values.")
        if len(set(normalised)) != len(normalised):
            raise ValueError("document_ids must not contain duplicates.")
        return normalised


class AnswerSource(BaseModel):
    chunk_id: str = Field(exclude=True)
    source_id: str
    document_id: str
    external_document_id: str | None = None
    document_title: str
    country: str | None = None
    language: str | None = None
    section_title: str | None = None
    page_number: int | None = None
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class AskResponse(BaseModel):
    answer: str
    sources: list[AnswerSource]
    confidence: Confidence
    uncertainty: str | None = None
    limitations: str = STANDARD_LIMITATION


def insufficient_evidence_response() -> AskResponse:
    return AskResponse(
        answer=INSUFFICIENT_EVIDENCE_ANSWER,
        sources=[],
        confidence="low",
        uncertainty=INSUFFICIENT_EVIDENCE_UNCERTAINTY,
        limitations=STANDARD_LIMITATION,
    )
