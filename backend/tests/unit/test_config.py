from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_upload_bytes": 0}, "MAX_UPLOAD_BYTES"),
        ({"chunk_size": 0}, "CHUNK_SIZE"),
        ({"chunk_overlap": -1}, "CHUNK_OVERLAP"),
        ({"chunk_size": 100, "chunk_overlap": 100}, "CHUNK_OVERLAP"),
        ({"ingestion_job_max_attempts": 0}, "INGESTION_JOB_MAX_ATTEMPTS"),
        ({"retrieval_min_similarity": -0.1}, "RETRIEVAL_MIN_SIMILARITY"),
        ({"retrieval_high_confidence_similarity": 1.1}, "RETRIEVAL_HIGH_CONFIDENCE_SIMILARITY"),
        (
            {"retrieval_min_similarity": 0.8, "retrieval_high_confidence_similarity": 0.7},
            "RETRIEVAL_HIGH_CONFIDENCE_SIMILARITY",
        ),
        ({"retrieval_cache_similarity_threshold": 1.1}, "RETRIEVAL_CACHE_SIMILARITY_THRESHOLD"),
        ({"retrieval_cache_ttl_seconds": 0}, "RETRIEVAL_CACHE_TTL_SECONDS"),
        ({"retrieval_cache_max_entries": 0}, "RETRIEVAL_CACHE_MAX_ENTRIES"),
        ({"retrieval_chunk_cache_max_entries": 0}, "RETRIEVAL_CHUNK_CACHE_MAX_ENTRIES"),
    ],
)
def test_settings_rejects_dangerous_operational_values(
    overrides: dict[str, int | float],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**overrides)


def test_settings_accepts_safe_operational_values() -> None:
    settings = Settings(
        max_upload_bytes=1,
        chunk_size=100,
        chunk_overlap=99,
        ingestion_job_max_attempts=1,
        retrieval_min_similarity=0.0,
        retrieval_high_confidence_similarity=1.0,
        retrieval_cache_similarity_threshold=1.0,
        retrieval_cache_ttl_seconds=1,
        retrieval_cache_max_entries=1,
        retrieval_chunk_cache_max_entries=1,
    )

    assert settings.ingestion_job_max_attempts == 1


def test_provider_defaults_use_real_gemini_providers() -> None:
    settings = Settings()

    assert settings.embedding_provider == "gemini"
    assert settings.embedding_model == "models/gemini-embedding-001"
    assert settings.embedding_dimension == 3072
    assert settings.llm_provider == "gemini"
    assert settings.chat_model == "gemini-3.5-flash"
