from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import STATUS_READY
from app.repositories.models import (
    Answer,
    Document,
    DocumentChunk,
    Question,
)
from app.repositories.models import (
    AnswerSource as AnswerSourceModel,
)
from app.schemas.answers import AnswerSource, AskResponse


@dataclass(frozen=True)
class SavedAnswer:
    question_id: str
    answer_id: str


class AnswerRepository(Protocol):
    async def count_ready_documents(
        self,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> int: ...

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
    ) -> SavedAnswer: ...

    async def delete_sources_by_document(self, workspace_id: str, document_id: str) -> None: ...


class PostgresAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_ready_documents(
        self,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> int:
        stmt = select(func.count()).select_from(Document).where(
            Document.workspace_id == workspace_id,
            Document.status == STATUS_READY,
        )

        if country:
            normalised_country = country.lower()
            stmt = stmt.where(
                (func.lower(Document.country) == normalised_country)
                | (func.lower(Document.country_code) == normalised_country)
            )

        if document_ids:
            stmt = stmt.where(Document.id.in_(document_ids))

        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

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
        question_id = str(uuid4())
        answer_id = str(uuid4())
        question_row = Question(
            id=question_id,
            workspace_id=workspace_id,
            question=question,
            country_filter=country_filter,
            document_ids_filter=json.dumps(document_ids_filter or []),
        )
        answer_row = Answer(
            id=answer_id,
            question_id=question_id,
            answer=response.answer,
            confidence=response.confidence,
            uncertainty=response.uncertainty,
            limitations=response.limitations,
            model_provider=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
            input_tokens=None,
            output_tokens=None,
            latency_ms=latency_ms,
        )
        self.session.add(question_row)
        self.session.add(answer_row)
        self.session.add_all(_source_rows(answer_id, response.sources))
        await self.session.commit()
        return SavedAnswer(question_id=question_id, answer_id=answer_id)

    async def delete_sources_by_document(self, workspace_id: str, document_id: str) -> None:
        chunk_ids = select(DocumentChunk.id).where(
            DocumentChunk.workspace_id == workspace_id,
            DocumentChunk.document_id == document_id,
        )
        await self.session.execute(
            delete(AnswerSourceModel).where(AnswerSourceModel.chunk_id.in_(chunk_ids))
        )
        await self.session.flush()


def _source_rows(answer_id: str, sources: list[AnswerSource]) -> list[AnswerSourceModel]:
    return [
        AnswerSourceModel(
            id=str(uuid4()),
            answer_id=answer_id,
            chunk_id=source.chunk_id,
            source_label=source.source_id,
            relevance_score=source.relevance_score,
            citation_order=index,
        )
        for index, source in enumerate(sources, start=1)
    ]
