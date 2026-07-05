"""FastAPI application factory.

``create_app`` takes an optional ``Settings`` override so tests can build a
fully isolated app instance (temp SQLite file, temp Chroma dir, mock
providers) without monkeypatching global state. See python/fastapi.md:
"Put app construction in create_app()".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes.ask import router as ask_router
from app.api.routes.auth import router as auth_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_context_middleware
from app.rag.embeddings import get_embedding_provider
from app.rag.llm_providers import create_answer_generator
from app.rag.retriever import ChromaRetriever
from app.repositories.database import build_engine, build_session_factory, create_all
from app.services.ingestion_worker import IngestionWorker
from app.storage.local import LocalStorageProvider
from app.vectorstores.chroma_store import ChromaVectorStore, build_chroma_resources


def _validate_auth_config(settings: Settings) -> None:
    if settings.auth_mode == "jwt" and not settings.jwt_secret:
        raise RuntimeError(
            "AUTH_MODE=jwt requires JWT_SECRET to be set. Refusing to start with an "
            "unsigned/guessable token configuration."
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    _validate_auth_config(resolved_settings)
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(resolved_settings.database_url)
        await create_all(engine)
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        app.state.storage_provider = LocalStorageProvider(resolved_settings.local_storage_dir)
        app.state.embedding_provider = get_embedding_provider(
            provider=resolved_settings.embedding_provider,
            openai_api_key=resolved_settings.openai_api_key,
            gemini_api_key=resolved_settings.gemini_api_key,
            model=resolved_settings.embedding_model,
        )
        chroma_resources = build_chroma_resources(
            resolved_settings.chroma_persist_dir,
            collection_name=resolved_settings.chroma_collection_name,
        )
        app.state.chroma_client = chroma_resources.client
        app.state.chroma_collection = chroma_resources.collection
        app.state.vector_store = ChromaVectorStore(chroma_resources.collection)
        app.state.retriever = ChromaRetriever(
            collection=chroma_resources.collection,
            min_similarity=resolved_settings.retrieval_min_similarity,
            final_context_count=resolved_settings.retrieval_context_count,
            max_chunks_per_document=resolved_settings.retrieval_max_chunks_per_document,
        )
        app.state.answer_generator = create_answer_generator(resolved_settings)
        app.state.ingestion_worker = None
        if resolved_settings.ingestion_worker_enabled:
            app.state.ingestion_worker = IngestionWorker(
                session_factory=app.state.session_factory,
                storage=app.state.storage_provider,
                embedding_provider=app.state.embedding_provider,
                vector_store=app.state.vector_store,
                settings=resolved_settings,
            )
            app.state.ingestion_worker.start()
        yield
        if app.state.ingestion_worker is not None:
            await app.state.ingestion_worker.stop()
        await engine.dispose()

    app = FastAPI(
        title="Market Access Evidence Assistant -- Ingestion API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins_list,
        # Auth is Bearer-token-in-header (JWT/API key), never cookies, so
        # credentialed CORS is unnecessary attack surface -- fetch/XHR can
        # send an Authorization header without credentials:"include".
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_context_middleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(ask_router)

    return app


app = create_app()
