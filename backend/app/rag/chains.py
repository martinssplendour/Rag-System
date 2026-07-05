from __future__ import annotations

from typing import Any

from app.rag.llm_providers import GroundedAnswer


def create_grounded_answer_chain(chat_model: Any) -> Any:
    try:
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise RuntimeError("langchain-core is not installed.") from exc

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            ("human", "{user_prompt}"),
        ]
    )
    return prompt | chat_model.with_structured_output(GroundedAnswer)
