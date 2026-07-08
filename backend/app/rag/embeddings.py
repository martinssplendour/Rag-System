"""Embedding provider abstraction.

The same provider instance is used to embed chunks during ingestion and
(by Part 2) to embed the incoming question at ask-time, so retrieval
compares vectors from a single consistent source. Do not add a second
embedding code path elsewhere in the app.
"""

from __future__ import annotations

import hashlib
import random
from typing import Protocol

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

# Retry only transient provider failures. Never retry auth failures (401),
# bad requests (400), or other 4xx errors -- see reliability rules in
# BUILD_SPEC_PART1_INGESTION.md / main build spec section 22.1.
_RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    from google.genai import errors as genai_errors

    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError):
        # 429 (rate limit) is the only 4xx worth retrying; 400/401/403 are
        # not transient.
        return getattr(exc, "code", None) == 429
    return False


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class MockEmbeddingProvider:
    """Deterministic, offline embedding provider for tests and demos.

    Not semantically meaningful -- the vectors are a seeded hash of the
    input text, so identical text always yields identical vectors and
    retrieval ordering is reproducible, but it does not capture real
    semantic similarity. Use ``EMBEDDING_PROVIDER=gemini`` or
    ``EMBEDDING_PROVIDER=openai`` for genuine semantic search.
    """

    dimension = 64

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        rng = random.Random(digest)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]


class OpenAIEmbeddingProvider:
    """Real embedding provider backed by the OpenAI API via langchain-openai.

    Retries only transient errors (rate limits, 5xx, timeouts) with bounded
    exponential backoff -- see security/reliability rules in the build spec.
    """

    def __init__(self, api_key: str, model: str) -> None:
        from langchain_openai import OpenAIEmbeddings

        self._client = OpenAIEmbeddings(model=model, api_key=api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        reraise=True,
    )
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        reraise=True,
    )
    async def embed_query(self, text: str) -> list[float]:
        return await self._client.aembed_query(text)


class GeminiEmbeddingProvider:
    """Real embedding provider backed by the Gemini API via
    langchain-google-genai.

    Retries only transient errors (5xx, 429 rate limits) with bounded
    exponential backoff -- see security/reliability rules in the build
    spec. Auth/invalid-request failures (400/401/403) are not retried.
    """

    def __init__(self, api_key: str, model: str) -> None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self._client = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception(_is_retryable_gemini_error),
        reraise=True,
    )
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception(_is_retryable_gemini_error),
        reraise=True,
    )
    async def embed_query(self, text: str) -> list[float]:
        return await self._client.aembed_query(text)


def get_embedding_provider(
    *,
    provider: str,
    model: str,
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
) -> EmbeddingProvider:
    normalised = provider.lower()
    if normalised == "mock":
        return MockEmbeddingProvider()
    if normalised == "openai":
        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        return OpenAIEmbeddingProvider(api_key=openai_api_key, model=model)
    if normalised == "gemini":
        if not gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini")
        return GeminiEmbeddingProvider(api_key=gemini_api_key, model=model)
    if normalised == "azure_openai":
        raise NotImplementedError(
            "azure_openai embedding provider is not implemented in the MVP; "
            "use 'mock', 'openai', or 'gemini', or add an AzureOpenAIEmbeddings-backed "
            "implementation here following the OpenAIEmbeddingProvider pattern."
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
