from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.rag.llm_providers import (
    LangChainAnswerGenerator,
    LLMProviderConfigurationError,
    MockAnswerGenerator,
    create_answer_generator,
)


class Settings:
    llm_provider = "mock"


@pytest.mark.anyio
async def test_mock_answer_generator_uses_valid_context_source_ids() -> None:
    generator = MockAnswerGenerator()

    answer = await generator.generate(
        question="What evidence exists?",
        context='<evidence source_id="UK-NICE-001">Alpha</evidence>',
    )

    assert answer.evidence_sufficient
    assert answer.source_ids == ["UK-NICE-001"]


def test_provider_factory_selects_mock() -> None:
    generator = create_answer_generator(Settings())

    assert isinstance(generator, MockAnswerGenerator)


def test_provider_factory_rejects_unknown_provider() -> None:
    settings = Settings()
    settings.llm_provider = "unknown"

    with pytest.raises(LLMProviderConfigurationError):
        create_answer_generator(settings)


def test_provider_factory_selects_gemini_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeChatGoogleGenerativeAI:
        def __init__(self, model: str, google_api_key: str) -> None:
            self.model = model
            self.google_api_key = google_api_key

        def with_structured_output(self, schema):  # type: ignore[no-untyped-def]
            del schema
            return self

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        SimpleNamespace(ChatGoogleGenerativeAI=FakeChatGoogleGenerativeAI),
    )
    settings = Settings()
    settings.llm_provider = "gemini"
    settings.chat_model = "gemini-test-model"
    settings.gemini_api_key = "test-key"

    generator = create_answer_generator(settings)

    assert isinstance(generator, LangChainAnswerGenerator)
    assert generator.provider_name == "gemini"
    assert generator.model_name == "gemini-test-model"
