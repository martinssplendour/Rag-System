from __future__ import annotations

import pytest

from app.core.config import Settings
from app.main import create_app
from app.rag.prompts import (
    PromptConfigurationError,
    build_repair_prompt,
    load_repair_instruction,
    load_system_prompt,
)


def test_system_prompt_loads_from_versioned_markdown_file() -> None:
    prompt = load_system_prompt("1.0.0")

    assert "Market Access Evidence Assistant" in prompt
    assert "Answer only from the supplied evidence excerpts" in prompt


def test_repair_prompt_loads_instruction_from_versioned_markdown_file() -> None:
    prompt = build_repair_prompt(
        question="What evidence exists?",
        context='<evidence source_id="S1">Alpha</evidence>',
        invalid_labels=["S9"],
        prompt_version="1.0.0",
    )

    assert load_repair_instruction("1.0.0") in prompt
    assert "Invalid labels from previous answer: S9" in prompt


def test_unknown_prompt_version_refuses_to_start() -> None:
    settings = Settings(prompt_version="does-not-exist")

    with pytest.raises(PromptConfigurationError, match="Unsupported PROMPT_VERSION"):
        create_app(settings)
