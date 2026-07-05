"""Shared FastAPI dependencies.

Providers are constructed once at app startup and stored on app.state
(see main.py's lifespan) so route handlers never instantiate long-lived
clients themselves -- see python/fastapi.md dependency-injection rule.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import Settings
from app.core.security import InvalidTokenError, decode_access_token
from app.rag.embeddings import EmbeddingProvider
from app.rag.llm_providers import AnswerGenerator
from app.rag.retriever import RetrievalService
from app.repositories.answers import AnswerRepository, PostgresAnswerRepository
from app.repositories.users import UserRepository
from app.services.evidence_assistant_service import EvidenceAssistantService
from app.storage.base import StorageProvider
from app.vectorstores.base import VectorStore

# auto_error=False so a missing token falls through to our own AppError
# (consistent error envelope) instead of FastAPI's default 403 with a
# differently-shaped body.
_bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger("market_access_evidence_assistant")


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    workspace_id: str
    email: str | None
    is_admin_claim: bool


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Resolve the caller's workspace.

    ``auth_mode=disabled`` (the local-dev/test default) always returns the
    fixed default workspace, preserving zero-friction local use.
    ``auth_mode=jwt`` requires a valid ``Authorization: Bearer <token>``
    header and returns the workspace_id claim from it -- this is what
    actually gives each registered user their own isolated data, since
    every document/chunk/answer query already filters by workspace_id.
    ``auth_mode=api_key`` is app-level protection for demos/integrations:
    callers send X-API-Key and use DEFAULT_WORKSPACE_ID.
    """
    settings = request.app.state.settings

    if settings.auth_mode == "disabled":
        return Principal(
            user_id=None,
            workspace_id=settings.default_workspace_id,
            email=None,
            is_admin_claim=True,
        )

    if settings.auth_mode == "jwt":
        if credentials is None:
            raise AppError("MISSING_TOKEN", "An Authorization Bearer token is required.", 401)
        try:
            claims = decode_access_token(
                credentials.credentials, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
            )
        except InvalidTokenError as exc:
            raise AppError("INVALID_TOKEN", "The provided token is invalid or expired.", 401) from exc
        workspace_id = claims.get("workspace_id")
        if not workspace_id:
            raise AppError("INVALID_TOKEN", "The provided token is missing a workspace claim.", 401)
        user_id = claims.get("sub")
        if not user_id:
            raise AppError("INVALID_TOKEN", "The provided token is missing a subject claim.", 401)
        return Principal(
            user_id=str(user_id),
            workspace_id=str(workspace_id),
            email=str(claims["email"]) if claims.get("email") else None,
            is_admin_claim=bool(claims.get("is_admin")),
        )

    if settings.auth_mode == "api_key":
        supplied_key = request.headers.get("X-API-Key", "")
        expected_key = settings.app_api_key or ""
        if not supplied_key:
            logger.warning("api_key_auth_failed reason=missing")
            raise AppError("UNAUTHORIZED", "Authentication required.", 401)
        if not secrets.compare_digest(supplied_key, expected_key):
            logger.warning("api_key_auth_failed reason=invalid")
            raise AppError("UNAUTHORIZED", "Authentication required.", 401)
        return Principal(
            user_id=None,
            workspace_id=settings.default_workspace_id,
            email=None,
            is_admin_claim=True,
        )

    raise AppError(
        "AUTH_MODE_NOT_SUPPORTED", f"Unsupported AUTH_MODE configured: {settings.auth_mode}", 500
    )


def get_workspace_id(principal: Principal = Depends(get_current_principal)) -> str:
    return principal.workspace_id


async def require_admin_upload(
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if settings.auth_mode == "disabled":
        return
    if settings.auth_mode == "api_key" and principal.is_admin_claim:
        return
    if principal.user_id is None:
        raise AppError("INVALID_TOKEN", "The provided token is missing a subject claim.", 401)

    user = await UserRepository(session).get_by_id(principal.user_id)
    if user is not None and not user.is_admin and user.email in settings.admin_email_set:
        user.is_admin = True
        await session.commit()
    if user is None or not user.is_admin:
        raise AppError("ADMIN_REQUIRED", "Only admin users can upload evidence documents.", 403)


def get_storage_provider(request: Request) -> StorageProvider:
    return request.app.state.storage_provider


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


def get_vector_store(request: Request) -> VectorStore:
    return request.app.state.vector_store


def get_retriever(request: Request) -> RetrievalService:
    return request.app.state.retriever


def get_answer_generator(request: Request) -> AnswerGenerator:
    return request.app.state.answer_generator


def get_answer_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AnswerRepository:
    return PostgresAnswerRepository(session)


def get_evidence_assistant_service(
    settings: Settings = Depends(get_settings),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    retriever: RetrievalService = Depends(get_retriever),
    answer_generator: AnswerGenerator = Depends(get_answer_generator),
    answer_repository: AnswerRepository = Depends(get_answer_repository),
) -> EvidenceAssistantService:
    return EvidenceAssistantService(
        embedding_provider=embedding_provider,
        retriever=retriever,
        answer_generator=answer_generator,
        answer_repository=answer_repository,
        settings=settings,
    )
