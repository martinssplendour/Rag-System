from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol

from app.rag.llm_providers import AnswerGenerator, GroundedAnswer
from app.rag.prompts import build_evidence_context, build_repair_prompt
from app.rag.retriever import (
    RetrievalService,
    assign_source_labels,
)
from app.repositories.answers import AnswerRepository
from app.schemas.answers import STANDARD_LIMITATION, AskResponse, insufficient_evidence_response
from app.services.citation_service import (
    source_cards_for_citations,
    validate_citations,
)
from app.services.confidence_service import calculate_confidence


class EmbeddingProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...


class EvidenceAssistantService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        retriever: RetrievalService,
        answer_generator: AnswerGenerator,
        answer_repository: AnswerRepository,
        settings: Any,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.retriever = retriever
        self.answer_generator = answer_generator
        self.answer_repository = answer_repository
        self.settings = settings

    async def ask(
        self,
        *,
        question: str,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> AskResponse:
        started = time.perf_counter()
        ready_count = await self.answer_repository.count_ready_documents(
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
        )
        if ready_count == 0:
            return await self._persist_and_return(
                response=insufficient_evidence_response(),
                question=question,
                workspace_id=workspace_id,
                country=country,
                document_ids=document_ids,
                latency_ms=_elapsed_ms(started),
            )

        query_embedding = await self.embedding_provider.embed_query(question)
        retrieved_chunks = await self.retriever.retrieve(
            query_embedding=query_embedding,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            candidate_count=_setting(self.settings, "retrieval_candidate_count", 12),
        )
        if not retrieved_chunks:
            return await self._persist_and_return(
                response=insufficient_evidence_response(),
                question=question,
                workspace_id=workspace_id,
                country=country,
                document_ids=document_ids,
                latency_ms=_elapsed_ms(started),
            )

        labeled_sources = assign_source_labels(retrieved_chunks)
        context = build_evidence_context(
            labeled_sources,
            max_context_chars=_setting(self.settings, "retrieval_max_context_chars", 12_000),
        )
        answer = await self.answer_generator.generate(question=question, context=context)
        validation = validate_citations(answer, labeled_sources)

        if not validation.is_valid:
            repair_prompt = build_repair_prompt(
                question=question,
                context=context,
                invalid_labels=validation.invalid_source_ids,
                prompt_version=str(_setting(self.settings, "prompt_version", "1.0.0")),
            )
            answer = await self.answer_generator.generate(question=repair_prompt, context=context)
            validation = validate_citations(answer, labeled_sources)

        if not validation.is_valid:
            return await self._persist_and_return(
                response=insufficient_evidence_response(),
                question=question,
                workspace_id=workspace_id,
                country=country,
                document_ids=document_ids,
                latency_ms=_elapsed_ms(started),
            )

        response = _build_response(
            answer=answer,
            cited_source_ids=validation.cited_source_ids,
            labeled_sources=labeled_sources,
            min_similarity=_setting(self.settings, "retrieval_min_similarity", 0.45),
            high_similarity=_setting(
                self.settings,
                "retrieval_high_confidence_similarity",
                0.75,
            ),
        )
        return await self._persist_and_return(
            response=response,
            question=question,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            latency_ms=_elapsed_ms(started),
        )

    async def _persist_and_return(
        self,
        *,
        response: AskResponse,
        question: str,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
        latency_ms: int,
    ) -> AskResponse:
        await self.answer_repository.save_answer(
            workspace_id=workspace_id,
            question=question,
            country_filter=country,
            document_ids_filter=document_ids,
            response=response,
            provider_name=getattr(self.answer_generator, "provider_name", "unknown"),
            model_name=getattr(self.answer_generator, "model_name", "unknown"),
            prompt_version=str(_setting(self.settings, "prompt_version", "1.0.0")),
            latency_ms=latency_ms,
        )
        return response


def _build_response(
    *,
    answer: GroundedAnswer,
    cited_source_ids: list[str],
    labeled_sources: Sequence[Any],
    min_similarity: float,
    high_similarity: float,
) -> AskResponse:
    source_cards = source_cards_for_citations(list(labeled_sources), cited_source_ids)
    confidence = calculate_confidence(
        evidence_sufficient=answer.evidence_sufficient,
        citation_validation_passed=True,
        cited_sources=source_cards,
        min_similarity=min_similarity,
        high_similarity=high_similarity,
    )
    return AskResponse(
        answer=answer.answer,
        sources=source_cards,
        confidence=confidence,
        uncertainty=answer.uncertainty,
        limitations=STANDARD_LIMITATION,
    )


def _setting(settings: Any, name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
