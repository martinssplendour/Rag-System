from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

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


class PostgresAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_tables(self) -> None:
        for statement in _DDL_STATEMENTS:
            await self.session.execute(text(statement))
        await self.session.commit()

    async def count_ready_documents(
        self,
        workspace_id: str,
        country: str | None,
        document_ids: list[str] | None,
    ) -> int:
        conditions = ["workspace_id = :workspace_id", "status = 'ready'"]
        params: dict[str, object] = {"workspace_id": workspace_id}

        if country:
            conditions.append(
                "(lower(country) = :country or lower(country_code) = :country)"
            )
            params["country"] = country.lower()

        statement = text(
            f"select count(*) from documents where {' and '.join(conditions)}"
        )
        if document_ids:
            statement = text(
                f"select count(*) from documents "
                f"where {' and '.join(conditions)} and id in :document_ids"
            ).bindparams(bindparam("document_ids", expanding=True))
            params["document_ids"] = document_ids

        result = await self.session.execute(statement, params)
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
        await self.ensure_tables()
        now = _utc_now()
        question_id = str(uuid4())
        answer_id = str(uuid4())

        await self.session.execute(
            text(
                """
                insert into questions (
                    id, workspace_id, question, country_filter,
                    document_ids_filter, created_at
                )
                values (
                    :id, :workspace_id, :question, :country_filter,
                    :document_ids_filter, :created_at
                )
                """
            ),
            {
                "id": question_id,
                "workspace_id": workspace_id,
                "question": question,
                "country_filter": country_filter,
                "document_ids_filter": json.dumps(document_ids_filter or []),
                "created_at": now,
            },
        )
        await self.session.execute(
            text(
                """
                insert into answers (
                    id, question_id, answer, confidence, uncertainty,
                    limitations, model_provider, model_name, prompt_version,
                    input_tokens, output_tokens, latency_ms, created_at
                )
                values (
                    :id, :question_id, :answer, :confidence, :uncertainty,
                    :limitations, :model_provider, :model_name, :prompt_version,
                    :input_tokens, :output_tokens, :latency_ms, :created_at
                )
                """
            ),
            {
                "id": answer_id,
                "question_id": question_id,
                "answer": response.answer,
                "confidence": response.confidence,
                "uncertainty": response.uncertainty,
                "limitations": response.limitations,
                "model_provider": provider_name,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "input_tokens": None,
                "output_tokens": None,
                "latency_ms": latency_ms,
                "created_at": now,
            },
        )
        await self._save_sources(answer_id, response.sources)
        await self.session.commit()
        return SavedAnswer(question_id=question_id, answer_id=answer_id)

    async def _save_sources(self, answer_id: str, sources: list[AnswerSource]) -> None:
        for index, source in enumerate(sources, start=1):
            await self.session.execute(
                text(
                    """
                    insert into answer_sources (
                        id, answer_id, chunk_id, source_label,
                        relevance_score, citation_order
                    )
                    values (
                        :id, :answer_id, :chunk_id, :source_label,
                        :relevance_score, :citation_order
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "answer_id": answer_id,
                    "chunk_id": source.chunk_id,
                    "source_label": source.source_id,
                    "relevance_score": source.relevance_score,
                    "citation_order": index,
                },
            )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


_DDL_STATEMENTS = [
    """
    create table if not exists questions (
        id text primary key,
        workspace_id text not null,
        question text not null,
        country_filter text,
        document_ids_filter text,
        created_at text not null
    )
    """,
    """
    create table if not exists answers (
        id text primary key,
        question_id text not null references questions(id) on delete cascade,
        answer text not null,
        confidence text not null check (confidence in ('high', 'medium', 'low')),
        uncertainty text,
        limitations text not null,
        model_provider text not null,
        model_name text not null,
        prompt_version text not null,
        input_tokens integer,
        output_tokens integer,
        latency_ms integer,
        created_at text not null
    )
    """,
    """
    create table if not exists answer_sources (
        id text primary key,
        answer_id text not null references answers(id) on delete cascade,
        chunk_id text not null references document_chunks(id),
        source_label text not null,
        relevance_score real not null,
        citation_order integer not null,
        unique (answer_id, source_label)
    )
    """,
]
