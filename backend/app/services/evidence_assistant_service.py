from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol

from app.rag.llm_providers import AnswerGenerator, GroundedAnswer
from app.rag.prompts import build_evidence_context, build_repair_prompt
from app.rag.query_decomposition import decompose_question
from app.rag.retriever import (
    LabeledChunk,
    RetrievalService,
    RetrievedChunk,
    assign_source_labels,
)
from app.repositories.answers import AnswerRepository
from app.schemas.answers import (
    STANDARD_LIMITATION,
    AskResponse,
    insufficient_evidence_response,
)
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

        sub_questions = decompose_question(question)
        if len(sub_questions) > 1:
            response = await self._answer_multiple_questions(
                questions=sub_questions,
                workspace_id=workspace_id,
                country=country,
                document_ids=document_ids,
            )
        else:
            response = await self._answer_question(
                question=question,
                workspace_id=workspace_id,
                country=country,
                document_ids=document_ids,
            )
        return await self._persist_and_return(
            response=response,
            question=question,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            latency_ms=_elapsed_ms(started),
        )

    async def _answer_multiple_questions(
        self,
        *,
        questions: list[str],
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> AskResponse:
        chunks_by_question: list[list[RetrievedChunk]] = []
        for sub_question in questions:
            chunks_by_question.append(
                await self._retrieve_chunks(
                    question=sub_question,
                    workspace_id=workspace_id,
                    country=country,
                    document_ids=document_ids,
                )
            )

        retrieved_chunks = _merge_retrieved_chunks(chunks_by_question)
        if not retrieved_chunks:
            return insufficient_evidence_response()

        labeled_sources = assign_source_labels(retrieved_chunks)
        source_ids_by_question = _source_ids_by_question(labeled_sources, chunks_by_question)
        context = build_evidence_context(
            labeled_sources,
            max_context_chars=_setting(self.settings, "retrieval_max_context_chars", 12_000),
        )
        multi_question_prompt = _build_multi_question_prompt(questions, source_ids_by_question)
        answer = await self.answer_generator.generate(question=multi_question_prompt, context=context)
        validation = validate_citations(answer, labeled_sources)

        if not validation.is_valid:
            repair_prompt = build_repair_prompt(
                question=multi_question_prompt,
                context=context,
                invalid_labels=validation.invalid_source_ids,
                prompt_version=str(_setting(self.settings, "prompt_version", "1.0.0")),
            )
            answer = await self.answer_generator.generate(question=repair_prompt, context=context)
            validation = validate_citations(answer, labeled_sources)

        if not validation.is_valid:
            return insufficient_evidence_response()

        return _build_response(
            answer=answer,
            cited_source_ids=validation.cited_source_ids,
            labeled_sources=labeled_sources,
            min_similarity=_setting(self.settings, "retrieval_min_similarity", 0.75),
            high_similarity=_setting(
                self.settings,
                "retrieval_high_confidence_similarity",
                0.75,
            ),
        )

    async def _answer_question(
        self,
        *,
        question: str,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> AskResponse:
        retrieved_chunks = await self._retrieve_chunks(
            question=question,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
        )
        if not retrieved_chunks:
            return insufficient_evidence_response()

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
            return insufficient_evidence_response()

        return _build_response(
            answer=answer,
            cited_source_ids=validation.cited_source_ids,
            labeled_sources=labeled_sources,
            min_similarity=_setting(self.settings, "retrieval_min_similarity", 0.75),
            high_similarity=_setting(
                self.settings,
                "retrieval_high_confidence_similarity",
                0.75,
            ),
        )

    async def _retrieve_chunks(
        self,
        *,
        question: str,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> list[RetrievedChunk]:
        query_embedding = await self.embedding_provider.embed_query(question)
        return await self.retriever.retrieve(
            query=question,
            query_embedding=query_embedding,
            workspace_id=workspace_id,
            country=country,
            document_ids=document_ids,
            candidate_count=_setting(self.settings, "retrieval_candidate_count", 12),
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


def _merge_retrieved_chunks(chunks_by_question: list[list[RetrievedChunk]]) -> list[RetrievedChunk]:
    merged: list[RetrievedChunk] = []
    seen: set[str] = set()
    for chunks in chunks_by_question:
        for chunk in chunks:
            if chunk.chunk_id in seen:
                continue
            merged.append(chunk)
            seen.add(chunk.chunk_id)
    return merged


def _source_ids_by_question(
    labeled_sources: list[LabeledChunk],
    chunks_by_question: list[list[RetrievedChunk]],
) -> list[list[str]]:
    source_id_by_chunk_id = {
        labeled.chunk.chunk_id: labeled.source_id for labeled in labeled_sources
    }
    grouped: list[list[str]] = []
    for chunks in chunks_by_question:
        source_ids: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            source_id = source_id_by_chunk_id.get(chunk.chunk_id)
            if source_id is None or source_id in seen:
                continue
            source_ids.append(source_id)
            seen.add(source_id)
        grouped.append(source_ids)
    return grouped


def _build_multi_question_prompt(
    questions: list[str],
    source_ids_by_question: list[list[str]],
) -> str:
    lines = [
        "The user asked multiple questions in one request.",
        "Answer each numbered sub-question separately in one response.",
        "For each sub-question, use only the source IDs listed for that sub-question.",
        "Do not cite source IDs outside the allowed list for that sub-question.",
        (
            "If a sub-question has no allowed source IDs, write exactly: "
            '"No sufficiently relevant source passages were retrieved for this sub-question."'
        ),
        "",
        "Sub-questions:",
    ]
    for index, (question, source_ids) in enumerate(
        zip(questions, source_ids_by_question, strict=True),
        start=1,
    ):
        allowed_sources = ", ".join(source_ids) if source_ids else "none"
        lines.append(f"{index}. {question}\nAllowed source IDs: {allowed_sources}")
    return "\n".join(lines)


def _setting(settings: Any, name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
