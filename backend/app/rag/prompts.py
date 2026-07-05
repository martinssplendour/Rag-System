from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from html import escape
from pathlib import Path

from app.rag.retriever import LabeledChunk

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_PROMPT_VERSION = "1.0.0"
_PROMPT_FILES_BY_VERSION = {
    "1.0.0": {
        "system": "market_access_answer_v1.md",
        "repair": "citation_repair_v1.md",
    }
}


class PromptConfigurationError(RuntimeError):
    pass


def load_system_prompt(prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    return _load_prompt(prompt_version, "system")


def load_repair_instruction(prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    return _load_prompt(prompt_version, "repair")


@lru_cache
def _load_prompt(prompt_version: str, prompt_kind: str) -> str:
    prompt_files = _PROMPT_FILES_BY_VERSION.get(prompt_version)
    if prompt_files is None:
        raise PromptConfigurationError(f"Unsupported PROMPT_VERSION: {prompt_version}")
    filename = prompt_files[prompt_kind]
    path = PROMPT_DIR / filename
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptConfigurationError(f"Prompt file not found: {path}") from exc
    if not prompt:
        raise PromptConfigurationError(f"Prompt file is empty: {path}")
    return prompt


SYSTEM_PROMPT = load_system_prompt()


def build_evidence_context(
    labeled_chunks: Sequence[LabeledChunk],
    max_context_chars: int = 12_000,
) -> str:
    blocks: list[str] = []
    used_chars = 0

    for labeled in labeled_chunks:
        chunk = labeled.chunk
        attributes = {
            "source_id": labeled.source_id,
            "title": chunk.title,
            "country": chunk.country or "",
            "language": chunk.language or "",
            "section": chunk.section_title or "",
            "page": "" if chunk.page_number is None else str(chunk.page_number),
        }
        attr_text = " ".join(
            f'{name}="{escape(value, quote=True)}"'
            for name, value in attributes.items()
        )
        evidence_text = escape(chunk.content.strip(), quote=False)
        block = f"<evidence {attr_text}>\n{evidence_text}\n</evidence>"

        if used_chars + len(block) > max_context_chars:
            remaining = max_context_chars - used_chars
            if remaining <= 0:
                break
            block = block[:remaining]

        blocks.append(block)
        used_chars += len(block)

    return "\n\n".join(blocks)


def build_user_prompt(question: str, context: str) -> str:
    return f"Question:\n{question}\n\nEvidence context:\n{context}"


def build_repair_prompt(
    question: str,
    context: str,
    invalid_labels: Sequence[str],
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> str:
    invalid = ", ".join(invalid_labels) if invalid_labels else "none"
    repair_instruction = load_repair_instruction(prompt_version)
    return (
        f"{repair_instruction}\nInvalid labels from previous answer: {invalid}\n\n"
        f"{build_user_prompt(question, context)}"
    )
