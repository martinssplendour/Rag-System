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
                answer="Invalid citation [UK-NICE-999]",
                source_ids=["UK-NICE-999"],
                evidence_sufficient=True,
            ),
            GroundedAnswer(
                answer="Valid citation [UK-NICE-001]",
                source_ids=["UK-NICE-001"],
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
    assert [source.source_id for source in response.sources] == ["UK-NICE-001"]


@pytest.mark.anyio
async def test_multi_question_request_runs_retrieval_per_sub_question() -> None:
    embedding_provider = FakeEmbeddingProvider()
    retriever = FakeRetriever([_chunk("chunk-1")])
    generator = FakeGenerator(
        [
            GroundedAnswer(
                answer=(
                    "1. The UK evidence gap was immature survival data [UK-NICE-001].\n\n"
                    "2. The Italian uncertainty was budget impact sensitivity [UK-NICE-001]."
                ),
                source_ids=["UK-NICE-001"],
                evidence_sufficient=True,
            ),
        ]
    )
    service = EvidenceAssistantService(
        embedding_provider=embedding_provider,
        retriever=retriever,
        answer_generator=generator,
        answer_repository=FakeRepository(ready_count=1),
        settings=Settings(),
    )

    response = await service.ask(
        question=(
            "What were the UK evidence gaps?\n"
            "Why was the Italian budget impact estimate uncertain?"
        ),
        workspace_id="workspace",
        country=None,
        document_ids=None,
    )

    assert embedding_provider.texts == [
        "What were the UK evidence gaps?",
        "Why was the Italian budget impact estimate uncertain?",
    ]
    assert retriever.queries == embedding_provider.texts
    assert generator.calls == 1
    assert "What were the UK evidence gaps?" in generator.questions[0]
    assert "Why was the Italian budget impact estimate uncertain?" in generator.questions[0]
    assert "Allowed source IDs: UK-NICE-001" in generator.questions[0]
    assert "1. The UK evidence gap" in response.answer
    assert "2. The Italian uncertainty" in response.answer
    assert response.confidence == "medium"
    assert [source.source_id for source in response.sources] == ["UK-NICE-001"]


class Settings:
    retrieval_candidate_count = 12
    retrieval_min_similarity = 0.75
    retrieval_high_confidence_similarity = 0.75
    prompt_version = "1.0.0"


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.texts.append(text)
        return [0.1, 0.2, 0.3]


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.queries: list[str] = []

    async def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        candidate_count: int,
    ) -> list[RetrievedChunk]:
        self.queries.append(query)
        del query_embedding, workspace_id, country, document_ids, candidate_count
        return self.chunks


class FakeGenerator:
    provider_name = "mock"
    model_name = "mock"

    def __init__(self, answers: list[GroundedAnswer]) -> None:
        self.answers = answers
        self.calls = 0
        self.questions: list[str] = []
        self.contexts: list[str] = []

    async def generate(
        self,
        question: str,
        context: str,
        response_language: str | None = None,
    ) -> GroundedAnswer:
        del response_language
        self.questions.append(question)
        self.contexts.append(context)
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
        country_code="UK",
        language="en",
        chunk_index=0,
        relevance_score=0.80,
        metadata={"workspace_id": "workspace", "status": "ready"},
    )
