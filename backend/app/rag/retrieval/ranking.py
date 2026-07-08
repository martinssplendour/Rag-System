from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from difflib import SequenceMatcher

from app.rag.retrieval.models import RetrievedChunk


def select_final_chunks(
    candidates: Sequence[RetrievedChunk],
    min_similarity: float,
    limit: int,
    max_chunks_per_document: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    per_document_count: dict[str, int] = defaultdict(int)

    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: candidate.relevance_score,
        reverse=True,
    )
    eligible_document_ids = {
        candidate.document_id
        for candidate in sorted_candidates
        if candidate.relevance_score >= min_similarity
    }
    enforce_document_cap = len(eligible_document_ids) > 1

    for candidate in sorted_candidates:
        if candidate.relevance_score < min_similarity:
            continue
        if candidate.chunk_id in seen_chunk_ids:
            continue
        if (
            enforce_document_cap
            and per_document_count[candidate.document_id] >= max_chunks_per_document
        ):
            continue
        if _is_near_duplicate(candidate, selected):
            continue

        selected.append(candidate)
        seen_chunk_ids.add(candidate.chunk_id)
        per_document_count[candidate.document_id] += 1

        if len(selected) >= limit:
            break

    return selected


def merge_candidates(*candidate_groups: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for candidates in candidate_groups:
        for candidate in candidates:
            existing = merged.get(candidate.chunk_id)
            if existing is None:
                merged[candidate.chunk_id] = candidate
                continue
            if candidate.relevance_score > existing.relevance_score:
                merged[candidate.chunk_id] = candidate
            elif candidate.relevance_score == existing.relevance_score:
                merged[candidate.chunk_id] = existing.model_copy(
                    update={"relevance_score": min(1.0, existing.relevance_score + 0.03)}
                )
    return list(merged.values())


def _is_near_duplicate(candidate: RetrievedChunk, selected: Sequence[RetrievedChunk]) -> bool:
    candidate_text = _normalise_for_similarity(candidate.raw_text or candidate.content)
    if not candidate_text:
        return False
    for existing in selected:
        existing_text = _normalise_for_similarity(existing.raw_text or existing.content)
        if candidate_text == existing_text:
            return True
        if SequenceMatcher(None, candidate_text, existing_text).ratio() >= 0.95:
            return True
    return False


def _normalise_for_similarity(value: str) -> str:
    return " ".join(value.lower().split())
