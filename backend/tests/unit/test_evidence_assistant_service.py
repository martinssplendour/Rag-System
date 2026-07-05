from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.rag.llm_providers import GroundedAnswer
from app.rag.retriever import RetrievedChunk
from app.repositories.answers import SavedAnswer
from app.schemas.answers import AskResponse
from app.services.evidence_assistant_service import EvidenceAssistantService


@pytest.mark.anyio
async def test_insufficient_evidence_does_not_call_llm() -> None:
    generator = FakeGenerator([])
    service = EvidenceAssistantService(
        embedding_provider=FakeEmbeddingProvider(),
        retriever=FakeRetriever([]),
        answer_generator=generator,
        answer_repository=FakeRepository(ready_count=0),
        settings=Settings(),
    )

    response = await service.ask(
        question="What was the global annual revenue?",
        workspace_id="workspace",
        country=None,
        document_ids=None,
    )

    assert response.confidence == "low"
    assert response.sources == []
    assert generator.calls == 0


@pytest.mark.anyio
async def test_invalid_citation_gets_one_repair_attempt() -> None:
    generator = FakeGenerator(
        [
            GroundedAnswer(
                answer="Invalid citation [S9]",
                source_ids=["S9"],
                evidence_sufficient=True,
            ),
            GroundedAnswer(
                answer="Valid citation [S1]",
                source_ids=["S1"],
                evidence_sufficient=True,
            ),
        ]
    )
    service = EvidenceAssistantService(
        embedding_provider=FakeEmbeddingProvider(),
        retriever=FakeRetriever([_chunk("chunk-1")]),
        answer_generator=generator,
        answer_repository=FakeRepository(ready_count=1),
        settings=Settings(),
    )

    response = await service.ask(
        question="Why was evidence uncertain?",
        workspace_id="workspace",
        country=None,
        document_ids=None,
    )

    assert generator.calls == 2
    assert response.confidence == "medium"
    assert [source.source_id for source in response.sources] == ["S1"]


class Settings:
    retrieval_candidate_count = 12
    retrieval_min_similarity = 0.45
    retrieval_high_confidence_similarity = 0.75
    prompt_version = "test"


class FakeEmbeddingProvider:
    async def embed_query(self, text: str) -> list[float]:
        del text
        return [0.1, 0.2, 0.3]


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks

    async def retrieve(
        self,
        query_embedding: list[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        del query_embedding, workspace_id, country, document_ids, candidate_count
        return self.chunks


class FakeGenerator:
    provider_name = "mock"
    model_name = "mock"

    def __init__(self, answers: list[GroundedAnswer]) -> None:
        self.answers = answers
        self.calls = 0

    async def generate(
        self,
        question: str,
        context: str,
        response_language: str | None = None,
    ) -> GroundedAnswer:
        del question, context, response_language
        self.calls += 1
        return self.answers.pop(0)


@dataclass
class FakeRepository:
    ready_count: int

    async def count_ready_documents(
        self,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> int:
        del workspace_id, country, document_ids
        return self.ready_count

    async def save_answer(
        self,
        workspace_id: str,
        question: str,
        country_filter: str | None,
        document_ids_filter: list[str] | None,
        response: AskResponse,
        provider_name: str,
        model_name: str,
        prompt_version: str,
        latency_ms: int,
    ) -> SavedAnswer:
        del (
            workspace_id,
            question,
            country_filter,
            document_ids_filter,
            response,
            provider_name,
            model_name,
            prompt_version,
            latency_ms,
        )
        return SavedAnswer(question_id="question-id", answer_id="answer-id")


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc-a",
        external_document_id="uk_nice_oncology_drug_summary",
        content="Overall survival was uncertain.",
        raw_text="Overall survival was uncertain.",
        title="UK NICE Oncology Drug Summary",
        country="United Kingdom",
        language="en",
        relevance_score=0.70,
        metadata={"workspace_id": "workspace", "status": "ready"},
    )
