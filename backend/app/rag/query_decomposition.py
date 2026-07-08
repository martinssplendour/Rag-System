from __future__ import annotations

import re

MAX_DECOMPOSED_QUESTIONS = 10

_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")
_LEADING_SEPARATOR_RE = re.compile(r"^\s*(?:[-:;]\s*)+")
_QUESTION_STARTS = {
    "are",
    "can",
    "compare",
    "could",
    "describe",
    "did",
    "do",
    "does",
    "explain",
    "how",
    "identify",
    "is",
    "list",
    "should",
    "summarise",
    "summarize",
    "tell",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "would",
}


def decompose_question(
    question: str,
    *,
    max_questions: int = MAX_DECOMPOSED_QUESTIONS,
) -> list[str]:
    text = _normalise_input(question)
    if not text:
        return []

    candidates = _split_on_lines(text)
    if len(candidates) <= 1:
        candidates = _split_on_question_marks(text)
    if len(candidates) <= 1:
        candidates = _split_on_dash_delimiter(text)

    cleaned = _clean_candidates(candidates)
    if len(cleaned) <= 1:
        return [text]
    return cleaned[:max_questions]


def _split_on_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return [text]

    parts: list[str] = []
    for line in lines:
        parts.extend(_split_on_question_marks(_strip_item_marker(line)))

    cleaned = _clean_candidates(parts)
    questionish_count = sum(1 for part in cleaned if _looks_like_question(part))
    if len(cleaned) >= 2 and questionish_count >= 2:
        return cleaned
    return [text]


def _split_on_question_marks(text: str) -> list[str]:
    matches = list(re.finditer(r"[^?]+\?", text))
    if len(matches) < 2:
        return [text]

    parts = [match.group(0) for match in matches]
    trailing = text[matches[-1].end() :].strip()
    if trailing and _looks_like_question(trailing):
        parts.append(trailing)
    return parts


def _split_on_dash_delimiter(text: str) -> list[str]:
    parts = re.split(r"\s+-\s+", text)
    cleaned = _clean_candidates(parts)
    if len(cleaned) >= 2 and all(_looks_like_question(part) for part in cleaned):
        return cleaned
    return [text]


def _clean_candidates(candidates: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalised = _clean_candidate(candidate)
        if not normalised or normalised in seen:
            continue
        cleaned.append(normalised)
        seen.add(normalised)
    return cleaned


def _clean_candidate(candidate: str) -> str:
    cleaned = _strip_item_marker(candidate)
    cleaned = _LEADING_SEPARATOR_RE.sub("", cleaned)
    return " ".join(cleaned.split()).strip()


def _strip_item_marker(value: str) -> str:
    return _LIST_MARKER_RE.sub("", value.strip())


def _looks_like_question(value: str) -> bool:
    cleaned = _clean_candidate(value)
    if cleaned.endswith("?"):
        return True
    words = re.findall(r"[a-z]+", cleaned.lower())
    return bool(words and words[0] in _QUESTION_STARTS)


def _normalise_input(value: str) -> str:
    lines = [line.strip() for line in value.strip().splitlines()]
    return "\n".join(line for line in lines if line)
