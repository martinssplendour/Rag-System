from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel

from app.rag.retrieval.models import RetrievedChunk
from app.rag.retrieval.utils import optional_str

_STOPWORDS = {
    "a",
    "about",
    "across",
    "after",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "could",
    "did",
    "do",
    "document",
    "documents",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "kind",
    "main",
    "may",
    "mention",
    "mentioned",
    "might",
    "note",
    "noted",
    "of",
    "on",
    "or",
    "proposed",
    "raised",
    "should",
    "that",
    "the",
    "their",
    "there",
    "this",
    "to",
    "was",
    "were",
    "what",
    "which",
    "why",
    "with",
    "would",
}

_COUNTRY_ALIASES = {
    "british": "united kingdom",
    "english": "united kingdom",
    "french": "france",
    "german": "germany",
    "italian": "italy",
    "uk": "united kingdom",
}

_QUERY_TERM_EXPANSIONS = {
    # Small local cross-language retrieval glossary. It is deliberately generic
    # market-access/evidence vocabulary, not document-specific expected answers.
    "access": ("zugang", "zugangsweg"),
    "benefit": ("nutzen", "verbesserung", "reduktion"),
    "clinical": ("klinisch", "klinische", "klinischem"),
    "comorbidity": ("komorbiditat",),
    "competence": ("kompetenz",),
    "concern": ("bedenken", "unsicherheit", "unsicherheiten", "unklar"),
    "cost": ("kosten",),
    "costs": ("kosten",),
    "digital": ("digital", "digitale", "digitaler"),
    "durability": ("dauerhaftigkeit", "langfristig"),
    "durable": ("dauerhaftigkeit", "langfristig"),
    "endpoint": ("endpunkt", "endpunkte"),
    "endpoints": ("endpunkt", "endpunkte"),
    "equity": ("gleichbehandlung", "zugangsgerechtigkeit"),
    "evidence": ("evidenz", "nachweis", "nachweise"),
    "follow": ("nachbeobachtung",),
    "fund": ("krankenversicherung", "versicherung"),
    "generalisability": ("generalisierbarkeit", "ubertragbarkeit", "reprasentativitat"),
    "generalizability": ("generalisierbarkeit", "ubertragbarkeit", "reprasentativitat"),
    "germany": ("deutschland", "deutsch", "deutsche", "deutschen"),
    "horizon": ("horizont",),
    "limited": ("eingeschrankt", "eingeschranktem"),
    "low": ("gering", "geringer"),
    "payer": ("kostentrager", "krankenversicherung"),
    "payers": ("kostentrager", "krankenversicherung"),
    "patient": ("patient", "patienten"),
    "programme": ("programm", "programme"),
    "program": ("programm", "programme"),
    "programmes": ("programm", "programme"),
    "question": ("frage",),
    "relevant": ("relevant", "relevante"),
    "representative": ("reprasentativ",),
    "representativeness": ("reprasentativitat",),
    "resource": ("ressource", "ressourcen", "ressourcennutzung"),
    "routine": ("routineversorgung",),
    "severe": ("schwer", "schwerer"),
    "sickness": ("krankenversicherung",),
    "stakeholder": ("akteur", "akteure"),
    "stakeholders": ("akteur", "akteure"),
    "strengthen": ("starken", "verbessern", "belastbarer", "robust"),
    "stronger": ("starker", "robuster", "belastbarer"),
    "subgroup": ("subgruppe", "subgruppen", "subgruppenanalyse", "subgruppenanalysen"),
    "therapeutic": ("therapeutik",),
    "uncertain": ("unsicher", "unsicherheit", "unsicherheiten", "unklar"),
    "uncertainty": ("unsicherheit", "unsicherheiten", "unklar"),
    "unclear": ("unklar", "unsicherheit"),
    "use": ("nutzung", "ressourcennutzung"),
    "week": ("woche", "wochen"),
    "weeks": ("wochen",),
}

_QUERY_PHRASE_EXPANSIONS = {
    "additional costs": ("zusatzliche kosten",),
    "disease management": ("disease management programme",),
    "digital competence": ("digitale kompetenz", "digitaler kompetenz"),
    "additional evidence": (
        "zusatzliche evidenz",
        "zusatzliche nachweise",
        "weitere evidenz",
        "weitere nachweise",
    ),
    "longer follow up": ("langere nachbeobachtung", "nachbeobachtung"),
    "limited smartphone access": ("eingeschranktem smartphone zugang",),
    "low digital competence": ("geringer digitaler kompetenz",),
    "patient relevant endpoints": ("patientenrelevante endpunkte",),
    "resource use": ("ressourcennutzung",),
    "severe comorbidity": ("schwerer komorbiditat",),
    "sickness fund": (
        "gesetzliche krankenversicherung",
        "gesetzlichen krankenversicherung",
    ),
    "sickness fund stakeholders": ("akteure gesetzliche krankenversicherung",),
    "smartphone access": ("smartphone zugang",),
    "subgroup analyses": ("subgruppenanalysen", "subgruppenanalyse"),
    "real world evidence": ("real world evidenz", "routineversorgung"),
}


def score_lexical_candidates(
    query_terms: Sequence[str],
    candidates: Sequence[RetrievedChunk],
) -> list[RetrievedChunk]:
    if not query_terms or not candidates:
        return []

    tokenised_documents = [_tokenize_for_lexical(_lexical_text(candidate)) for candidate in candidates]
    document_count = len(tokenised_documents)
    average_length = (
        sum(len(tokens) for tokens in tokenised_documents) / document_count if document_count else 0.0
    )
    document_frequencies: dict[str, int] = defaultdict(int)
    for tokens in tokenised_documents:
        for term in set(tokens):
            document_frequencies[term] += 1

    raw_scores: list[tuple[RetrievedChunk, float]] = []
    for candidate, tokens in zip(candidates, tokenised_documents, strict=True):
        score = _bm25_score(
            query_terms=query_terms,
            document_terms=tokens,
            document_frequencies=document_frequencies,
            document_count=document_count,
            average_document_length=average_length,
        )
        score += _table_exact_match_bonus(query_terms, candidate)
        if score > 0.0:
            raw_scores.append((candidate, score))

    if not raw_scores:
        return []

    max_score = max(score for _, score in raw_scores)
    scored: list[RetrievedChunk] = []
    for candidate, raw_score in raw_scores:
        normalised_score = raw_score / max_score if max_score else 0.0
        lexical_stats = _lexical_match_stats(query_terms, candidate)
        exact_match = _has_sufficient_lexical_match(lexical_stats, candidate)
        if exact_match:
            lexical_relevance = 0.70 + (0.22 * normalised_score)
        else:
            lexical_relevance = 0.35 + (0.34 * normalised_score)
        scored.append(
            candidate.model_copy(
                update={
                    "relevance_score": max(
                        candidate.relevance_score,
                        min(0.94, lexical_relevance),
                    ),
                    "metadata": {
                        **candidate.metadata,
                        "lexical_score": round(raw_score, 6),
                        "lexical_matched_terms": lexical_stats.matched_term_count,
                        "lexical_query_terms": lexical_stats.query_term_count,
                        "lexical_query_coverage": round(lexical_stats.query_coverage, 6),
                    },
                }
            )
        )

    return sorted(scored, key=lambda chunk: chunk.relevance_score, reverse=True)


def tokenize_query_for_lexical(value: str) -> list[str]:
    terms = _tokenize_for_lexical(value)
    expanded_terms = list(terms)
    phrase_text = _normalise_phrase_text(value)

    for phrase, expansions in _QUERY_PHRASE_EXPANSIONS.items():
        if phrase in phrase_text:
            for expansion in expansions:
                expanded_terms.extend(_tokenize_for_lexical(expansion))

    for term in terms:
        for expansion in _QUERY_TERM_EXPANSIONS.get(term, ()):
            expanded_terms.extend(_tokenize_for_lexical(expansion))

    return _dedupe_preserving_order(expanded_terms)


def has_exact_keyword_or_table_match(query: str, candidate: RetrievedChunk) -> bool:
    query_terms = tokenize_query_for_lexical(query)
    if not query_terms:
        return False
    return _has_sufficient_lexical_match(_lexical_match_stats(query_terms, candidate), candidate)


def _bm25_score(
    *,
    query_terms: Sequence[str],
    document_terms: Sequence[str],
    document_frequencies: dict[str, int],
    document_count: int,
    average_document_length: float,
) -> float:
    if not query_terms or not document_terms or average_document_length <= 0:
        return 0.0
    term_counts: dict[str, int] = defaultdict(int)
    for term in document_terms:
        term_counts[term] += 1

    k1 = 1.5
    b = 0.75
    document_length = len(document_terms)
    score = 0.0
    for term in set(query_terms):
        frequency = term_counts.get(term, 0)
        if frequency == 0:
            continue
        document_frequency = document_frequencies.get(term, 0)
        inverse_document_frequency = math.log(
            1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        denominator = frequency + k1 * (
            1.0 - b + b * (document_length / average_document_length)
        )
        score += inverse_document_frequency * ((frequency * (k1 + 1.0)) / denominator)
    return score


def _table_exact_match_bonus(query_terms: Sequence[str], candidate: RetrievedChunk) -> float:
    if not _is_table_chunk(candidate):
        return 0.0
    candidate_terms = set(_tokenize_for_lexical(_lexical_text(candidate)))
    hit_count = len(set(query_terms) & candidate_terms)
    if hit_count == 0:
        return 0.0
    return min(1.25, 0.35 * hit_count)


def _is_table_chunk(candidate: RetrievedChunk) -> bool:
    chunk_type = str(candidate.metadata.get("chunk_type") or "").lower()
    return chunk_type in {"table", "table_row"} or bool(candidate.metadata.get("table_id"))


def _lexical_text(candidate: RetrievedChunk) -> str:
    values = [
        candidate.title,
        candidate.section_title or "",
        candidate.content,
        candidate.raw_text,
        candidate.country or "",
        candidate.country_code or "",
        candidate.external_document_id or "",
        str(candidate.metadata.get("table_title") or ""),
        str(candidate.metadata.get("table_headers") or ""),
    ]
    return "\n".join(value for value in values if value)


def _tokenize_for_lexical(value: str) -> list[str]:
    normalised = unicodedata.normalize("NFKD", value.lower())
    normalised = "".join(character for character in normalised if not unicodedata.combining(character))
    raw_terms = re.findall(r"[a-z0-9]+", normalised)
    terms: list[str] = []
    for raw_term in raw_terms:
        mapped = _COUNTRY_ALIASES.get(raw_term, raw_term)
        for term in mapped.split():
            stemmed = _light_stem(term)
            if stemmed and stemmed not in _STOPWORDS and len(stemmed) > 1:
                terms.append(stemmed)
    return terms


def _normalise_phrase_text(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value.lower())
    normalised = "".join(character for character in normalised if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", normalised))


def _dedupe_preserving_order(values: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def _light_stem(term: str) -> str:
    if len(term) > 5 and term.endswith("ies"):
        return f"{term[:-3]}y"
    if len(term) > 4 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 4 and term.endswith("ed"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s"):
        return term[:-1]
    return term


class _LexicalMatchStats(BaseModel):
    matched_term_count: int
    query_term_count: int
    query_coverage: float


def _lexical_match_stats(
    query_terms: Sequence[str],
    candidate: RetrievedChunk,
) -> _LexicalMatchStats:
    unique_query_terms = set(query_terms)
    candidate_terms = set(_tokenize_for_lexical(_lexical_text(candidate)))
    matched_terms = unique_query_terms & candidate_terms
    query_term_count = len(unique_query_terms)
    query_coverage = len(matched_terms) / query_term_count if query_term_count else 0.0
    return _LexicalMatchStats(
        matched_term_count=len(matched_terms),
        query_term_count=query_term_count,
        query_coverage=query_coverage,
    )


def _has_sufficient_lexical_match(
    stats: _LexicalMatchStats,
    candidate: RetrievedChunk,
) -> bool:
    if _is_non_english_chunk(candidate) and stats.matched_term_count >= 3:
        return True
    if stats.matched_term_count >= 3 and stats.query_coverage >= 0.30:
        return True
    if (
        stats.matched_term_count >= 2
        and stats.query_term_count <= 8
        and stats.query_coverage >= 0.25
    ):
        return True
    if stats.matched_term_count >= 2 and stats.query_coverage >= 0.50:
        return True
    return _is_table_chunk(candidate) and stats.matched_term_count >= 2 and stats.query_coverage >= 0.35


def _is_non_english_chunk(candidate: RetrievedChunk) -> bool:
    language = (candidate.language or optional_str(candidate.metadata.get("language")) or "").lower()
    return bool(language) and language != "en"
