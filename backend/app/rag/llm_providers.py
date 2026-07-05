from __future__ import annotations

import asyncio
import os
import random
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from app.rag.prompts import build_user_prompt, load_system_prompt
from app.schemas.answers import INSUFFICIENT_EVIDENCE_ANSWER


class GroundedAnswer(BaseModel):
    answer: str
    source_ids: list[str] = Field(default_factory=list)
    evidence_sufficient: bool
    uncertainty: str | None = None

    @field_validator("source_ids")
    @classmethod
    def normalise_source_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        normalised: list[str] = []
        for item in value:
            source_id = item.strip()
            if source_id and source_id not in seen:
                normalised.append(source_id)
                seen.add(source_id)
        return normalised


class AnswerGenerator(Protocol):
    provider_name: str
    model_name: str

    async def generate(
        self,
        question: str,
        context: str,
        response_language: str | None = None,
    ) -> GroundedAnswer: ...


class LLMProviderError(RuntimeError):
    pass


class LLMProviderConfigurationError(LLMProviderError):
    pass


class MockAnswerGenerator:
    provider_name = "mock"
    model_name = "mock-grounded-answer"

    async def generate(
        self,
        question: str,
        context: str,
        response_language: str | None = None,
    ) -> GroundedAnswer:
        del question, response_language
        source_ids = _extract_source_ids(context)
        if not source_ids:
            return GroundedAnswer(
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                source_ids=[],
                evidence_sufficient=False,
                uncertainty="No evidence context was supplied.",
            )
        cited = source_ids[: min(2, len(source_ids))]
        citation_text = "".join(f"[{source_id}]" for source_id in cited)
        return GroundedAnswer(
            answer=f"The retrieved evidence supports a grounded answer. {citation_text}",
            source_ids=cited,
            evidence_sufficient=True,
            uncertainty=None,
        )


class LangChainAnswerGenerator:
    def __init__(
        self,
        chat_model: Any,
        provider_name: str,
        model_name: str,
        timeout_seconds: int,
        max_retries: int,
        system_prompt: str,
    ) -> None:
        self.chat_model = chat_model
        self.provider_name = provider_name
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.system_prompt = system_prompt

    async def generate(
        self,
        question: str,
        context: str,
        response_language: str | None = None,
    ) -> GroundedAnswer:
        del response_language
        chain = self._chain()
        payload = {
            "system_prompt": self.system_prompt,
            "user_prompt": build_user_prompt(question, context),
        }
        return await self._invoke_with_retries(chain, payload)

    def _chain(self) -> Any:
        try:
            from langchain_core.prompts import ChatPromptTemplate
        except ImportError as exc:  # pragma: no cover - exercised only without deps
            raise LLMProviderConfigurationError("langchain-core is not installed.") from exc

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                ("human", "{user_prompt}"),
            ]
        )
        return prompt | self.chat_model.with_structured_output(GroundedAnswer)

    async def _invoke_with_retries(self, chain: Any, payload: dict[str, str]) -> GroundedAnswer:
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    chain.ainvoke(payload),
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                if attempt >= attempts - 1 or not _is_retryable(exc):
                    raise LLMProviderError("Answer generation failed safely.") from exc
                await asyncio.sleep(_retry_delay(attempt))
        raise LLMProviderError("Answer generation failed safely.")


def create_answer_generator(settings: Any) -> AnswerGenerator:
    provider = str(getattr(settings, "llm_provider", "mock")).lower()
    timeout_seconds = int(getattr(settings, "llm_timeout_seconds", 45))
    max_retries = int(getattr(settings, "llm_max_retries", 2))
    system_prompt = load_system_prompt(str(getattr(settings, "prompt_version", "1.0.0")))

    if provider == "mock":
        return MockAnswerGenerator()
    if provider == "openai":
        return _create_openai_generator(settings, timeout_seconds, max_retries, system_prompt)
    if provider == "azure_openai":
        return _create_azure_generator(settings, timeout_seconds, max_retries, system_prompt)
    if provider in {"gemini", "google", "google_genai"}:
        return _create_gemini_generator(settings, timeout_seconds, max_retries, system_prompt)
    raise LLMProviderConfigurationError(f"Unsupported LLM_PROVIDER: {provider}")


def _create_openai_generator(
    settings: Any,
    timeout_seconds: int,
    max_retries: int,
    system_prompt: str,
) -> LangChainAnswerGenerator:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise LLMProviderConfigurationError("langchain-openai is not installed.") from exc

    model = str(getattr(settings, "chat_model", "") or "")
    if not model:
        raise LLMProviderConfigurationError("CHAT_MODEL is required for OpenAI mode.")
    chat_model = ChatOpenAI(
        model=model,
        api_key=getattr(settings, "openai_api_key", None),
        timeout=timeout_seconds,
        max_retries=0,
    )
    return LangChainAnswerGenerator(
        chat_model=chat_model,
        provider_name="openai",
        model_name=model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        system_prompt=system_prompt,
    )


def _create_azure_generator(
    settings: Any,
    timeout_seconds: int,
    max_retries: int,
    system_prompt: str,
) -> LangChainAnswerGenerator:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise LLMProviderConfigurationError("langchain-openai is not installed.") from exc

    deployment = str(getattr(settings, "azure_openai_chat_deployment", "") or "")
    if not deployment:
        raise LLMProviderConfigurationError(
            "AZURE_OPENAI_CHAT_DEPLOYMENT is required for Azure OpenAI mode."
        )
    chat_model = AzureChatOpenAI(
        azure_deployment=deployment,
        azure_endpoint=getattr(settings, "azure_openai_endpoint", None),
        api_key=getattr(settings, "azure_openai_api_key", None),
        api_version=getattr(settings, "azure_openai_api_version", None),
        timeout=timeout_seconds,
        max_retries=0,
    )
    return LangChainAnswerGenerator(
        chat_model=chat_model,
        provider_name="azure_openai",
        model_name=deployment,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        system_prompt=system_prompt,
    )


def _create_gemini_generator(
    settings: Any,
    timeout_seconds: int,
    max_retries: int,
    system_prompt: str,
) -> LangChainAnswerGenerator:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise LLMProviderConfigurationError(
            "langchain-google-genai is not installed."
        ) from exc

    model = str(_setting_or_env(settings, "chat_model", "CHAT_MODEL") or "")
    api_key = str(
        _setting_or_env(settings, "gemini_api_key", "GEMINI_API_KEY")
        or _setting_or_env(settings, "google_api_key", "GOOGLE_API_KEY")
        or ""
    )
    if not model:
        raise LLMProviderConfigurationError("CHAT_MODEL is required for Gemini mode.")
    if not api_key:
        raise LLMProviderConfigurationError(
            "GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini mode."
        )

    chat_model = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
    )
    return LangChainAnswerGenerator(
        chat_model=chat_model,
        provider_name="gemini",
        model_name=model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        system_prompt=system_prompt,
    )


def _setting_or_env(settings: Any, setting_name: str, env_name: str) -> Any:
    value = getattr(settings, setting_name, None)
    if value is not None and str(value).strip():
        return value
    return os.environ.get(env_name)


def _extract_source_ids(context: str) -> list[str]:
    source_ids = re.findall(r'source_id="(S\d+)"', context)
    seen: set[str] = set()
    unique: list[str] = []
    for source_id in source_ids:
        if source_id not in seen:
            unique.append(source_id)
            seen.add(source_id)
    return unique


def _is_retryable(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or (isinstance(status_code, int) and 500 <= status_code <= 599):
        return True
    error_text = str(exc).lower()
    return "timeout" in error_text or "temporarily unavailable" in error_text


def _retry_delay(attempt: int) -> float:
    base = min(2**attempt, 8)
    return base + random.uniform(0.0, 0.25)
