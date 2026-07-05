"""Unit tests for the embedding provider factory and mock provider."""

import pytest

from app.rag.embeddings import (
    GeminiEmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)


def test_get_embedding_provider_returns_mock():
    provider = get_embedding_provider(provider="mock", model="unused")
    assert isinstance(provider, MockEmbeddingProvider)


def test_get_embedding_provider_returns_openai_when_key_present():
    provider = get_embedding_provider(
        provider="openai", openai_api_key="sk-test", model="text-embedding-3-small"
    )
    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_get_embedding_provider_rejects_openai_without_key():
    with pytest.raises(RuntimeError):
        get_embedding_provider(provider="openai", model="text-embedding-3-small")


def test_get_embedding_provider_returns_gemini_when_key_present():
    provider = get_embedding_provider(
        provider="gemini", gemini_api_key="AIza-test", model="models/text-embedding-004"
    )
    assert isinstance(provider, GeminiEmbeddingProvider)


def test_get_embedding_provider_rejects_gemini_without_key():
    with pytest.raises(RuntimeError):
        get_embedding_provider(provider="gemini", model="models/text-embedding-004")


def test_get_embedding_provider_azure_not_implemented():
    with pytest.raises(NotImplementedError):
        get_embedding_provider(provider="azure_openai", openai_api_key="sk-test", model="unused")


def test_get_embedding_provider_rejects_unknown_provider():
    with pytest.raises(ValueError):
        get_embedding_provider(provider="not-a-real-provider", model="unused")


async def test_mock_embedding_provider_is_deterministic():
    provider = MockEmbeddingProvider()
    first = await provider.embed_query("What were the evidence gaps?")
    second = await provider.embed_query("What were the evidence gaps?")
    assert first == second


async def test_mock_embedding_provider_differs_for_different_text():
    provider = MockEmbeddingProvider()
    first = await provider.embed_query("question one")
    second = await provider.embed_query("question two")
    assert first != second


async def test_mock_embedding_provider_embed_documents_batches_correctly():
    provider = MockEmbeddingProvider()
    vectors = await provider.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(len(vector) == MockEmbeddingProvider.dimension for vector in vectors)
