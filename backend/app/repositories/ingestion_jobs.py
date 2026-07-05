from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    INGESTION_JOB_FAILED,
    INGESTION_JOB_PENDING,
    INGESTION_JOB_RUNNING,
    INGESTION_JOB_SUCCEEDED,
)
from app.repositories.models import IngestionJob


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, workspace_id: str, document_id: str) -> IngestionJob:
        job = IngestionJob(
            id=uuid4().hex,
            workspace_id=workspace_id,
            document_id=document_id,
            status=INGESTION_JOB_PENDING,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def claim_next_pending(self) -> IngestionJob | None:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.status == INGESTION_JOB_PENDING)
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .limit(1)
        )
        job = (await self._session.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None
        now = _utcnow()
        job.status = INGESTION_JOB_RUNNING
        job.attempts += 1
        job.locked_at = now
        job.started_at = now
        job.error_message = None
        await self._session.flush()
        return job

    async def get(self, job_id: str) -> IngestionJob | None:
        return await self._session.get(IngestionJob, job_id)

    async def get_latest_for_document(self, document_id: str) -> IngestionJob | None:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_succeeded(self, job: IngestionJob) -> None:
        job.status = INGESTION_JOB_SUCCEEDED
        job.completed_at = _utcnow()
        job.error_message = None
        await self._session.flush()

    async def mark_failed(self, job: IngestionJob, *, error_message: str) -> None:
        job.status = INGESTION_JOB_FAILED
        job.completed_at = _utcnow()
        job.error_message = error_message
        await self._session.flush()
