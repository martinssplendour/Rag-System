"""Typed application settings.

All paths default to locations under the backend package root so behaviour
is independent of the process's current working directory -- the app and
the seed script must agree on where ./data lives regardless of how each is
invoked.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    # env_file is anchored to BACKEND_ROOT (not left as a bare ".env") so it
    # is found regardless of the process's current working directory --
    # e.g. scripts/seed_dataset.py is documented to run from the repository
    # root, one level above backend/, where a relative ".env" would never
    # resolve. Caught via a live run that silently fell back to the mock
    # embedding provider instead of the gemini provider configured in
    # backend/.env.
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    database_url: str = f"sqlite+aiosqlite:///{(DEFAULT_DATA_DIR / 'app.db').as_posix()}"
    storage_backend: str = "local"
    local_storage_dir: Path = DEFAULT_DATA_DIR / "uploads"
    chroma_persist_dir: Path = DEFAULT_DATA_DIR / "chroma"

    auth_mode: str = "disabled"
    app_api_key: str = "change-me"
    default_workspace_id: str = "00000000-0000-0000-0000-000000000001"
    admin_emails: str = ""

    # JWT (auth_mode="jwt"): self-issued tokens, no external identity
    # provider. jwt_secret has no safe default -- it is validated at
    # startup in main.py when auth_mode="jwt" so the app refuses to run
    # with a missing/placeholder signing key.
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60

    embedding_provider: str = "mock"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    max_upload_bytes: int = 10_485_760
    max_direct_text_chars: int = 200_000
    chunk_size: int = 1000
    chunk_overlap: int = 150

    ingestion_worker_enabled: bool = True
    ingestion_worker_poll_seconds: float = 0.25
    ingestion_job_max_attempts: int = 3

    # Part 2 (retrieval/answer generation) settings. Declared here -- not
    # just read via getattr(settings, name, default) -- because
    # pydantic-settings with extra="ignore" silently drops any .env
    # variable that isn't a declared field. Without these, LLM_PROVIDER=
    # gemini/CHAT_MODEL in .env would never actually reach Settings, and
    # /ask would silently fall back to the mock provider despite .env
    # saying otherwise. See BUILD_SPEC_PART2_RETRIEVAL_AND_ANSWER.md
    # section 7 for the canonical list of these variables.
    llm_provider: str = "mock"
    chat_model: str | None = None
    llm_timeout_seconds: int = 45
    llm_max_retries: int = 2
    google_api_key: str | None = None

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str | None = None
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None

    chroma_collection_name: str = "market_access_chunks"
    retrieval_candidate_count: int = 12
    retrieval_context_count: int = 5
    retrieval_min_similarity: float = 0.45
    retrieval_high_confidence_similarity: float = 0.75
    retrieval_max_chunks_per_document: int = 3
    retrieval_max_context_chars: int = 12_000
    retrieval_cache_enabled: bool = True
    retrieval_cache_ttl_seconds: int = 900
    retrieval_cache_max_entries: int = 256
    retrieval_cache_similarity_threshold: float = 0.97
    retrieval_chunk_cache_max_entries: int = 1024
    prompt_version: str = "1.0.0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}

    @model_validator(mode="after")
    def validate_operational_bounds(self) -> Settings:
        _require_positive("MAX_UPLOAD_BYTES", self.max_upload_bytes)
        _require_positive("MAX_DIRECT_TEXT_CHARS", self.max_direct_text_chars)
        _require_positive("CHUNK_SIZE", self.chunk_size)
        _require_non_negative("CHUNK_OVERLAP", self.chunk_overlap)
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")

        _require_positive("INGESTION_WORKER_POLL_SECONDS", self.ingestion_worker_poll_seconds)
        if self.ingestion_job_max_attempts < 1:
            raise ValueError("INGESTION_JOB_MAX_ATTEMPTS must be at least 1")

        _require_probability("RETRIEVAL_MIN_SIMILARITY", self.retrieval_min_similarity)
        _require_probability(
            "RETRIEVAL_HIGH_CONFIDENCE_SIMILARITY",
            self.retrieval_high_confidence_similarity,
        )
        _require_probability(
            "RETRIEVAL_CACHE_SIMILARITY_THRESHOLD",
            self.retrieval_cache_similarity_threshold,
        )
        if self.retrieval_high_confidence_similarity < self.retrieval_min_similarity:
            raise ValueError(
                "RETRIEVAL_HIGH_CONFIDENCE_SIMILARITY must be greater than or equal to "
                "RETRIEVAL_MIN_SIMILARITY"
            )

        _require_positive("RETRIEVAL_CANDIDATE_COUNT", self.retrieval_candidate_count)
        _require_positive("RETRIEVAL_CONTEXT_COUNT", self.retrieval_context_count)
        _require_positive("RETRIEVAL_MAX_CHUNKS_PER_DOCUMENT", self.retrieval_max_chunks_per_document)
        _require_positive("RETRIEVAL_MAX_CONTEXT_CHARS", self.retrieval_max_context_chars)
        _require_positive("RETRIEVAL_CACHE_TTL_SECONDS", self.retrieval_cache_ttl_seconds)
        _require_positive("RETRIEVAL_CACHE_MAX_ENTRIES", self.retrieval_cache_max_entries)
        _require_positive(
            "RETRIEVAL_CHUNK_CACHE_MAX_ENTRIES",
            self.retrieval_chunk_cache_max_entries,
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _require_positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_non_negative(name: str, value: int | float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_probability(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
