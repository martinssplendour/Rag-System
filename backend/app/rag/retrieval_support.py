"""Language-specific retrieval hints added to searchable chunk text.

These hints are not citation text and are never shown as snippets. They make
cross-language retrieval less brittle while preserving the original source text
in ``raw_text`` for auditability.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace

from app.rag.chunking import ChunkDraft

_GERMAN_TERM_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("zusatzliche evidenz", "zusatzliche nachweise", "weitere evidenz", "weitere nachweise"),
        ("additional evidence", "further evidence"),
    ),
    (
        (
            "zentrale unsicherheiten",
            "dossier ware uberzeugender",
            "robuster deutscher evidenz",
            "robuste deutsche evidenz",
        ),
        ("key evidence gaps", "stronger dossier", "strengthen dossier"),
    ),
    (("nachbeobachtung",), ("longer follow-up", "long-term follow-up")),
    (("langfristig", "langfristige", "dauerhaftigkeit"), ("long-term durability",)),
    (("subgruppenanalyse", "subgruppenanalysen", "subgruppen"), ("subgroup analyses",)),
    (("patientenrelevant", "patientenrelevante endpunkte"), ("patient-relevant endpoints",)),
    (
        ("real world evidenz", "routineversorgung", "versorgungsrealitat"),
        ("real-world evidence", "routine care evidence"),
    ),
    (("standardversorgung",), ("standard care",)),
    (("schriftliche schulungsmaterialien",), ("written training materials",)),
    (
        ("strukturierte deutsche programme", "strukturierten deutschen programmen"),
        ("structured German programmes",),
    ),
    (("eingeschranktem smartphone zugang", "smartphone zugang"), ("limited smartphone access",)),
    (("schwerer komorbiditat",), ("severe comorbidity",)),
    (("geringer digitaler kompetenz",), ("low digital competence",)),
    (("gleichbehandlung", "zugangsgerechtigkeit"), ("equity and access",)),
    (("generalisierbarkeit", "ubertragbarkeit", "reprasentativitat"), ("generalisability",)),
    (
        ("gesetzliche krankenversicherung", "gesetzlichen krankenversicherung"),
        ("sickness-fund stakeholders",),
    ),
    (("ressourcennutzung",), ("resource use",)),
)


def add_english_retrieval_support(drafts: Sequence[ChunkDraft], *, language: str) -> list[ChunkDraft]:
    """Append English aliases to German chunk ``content`` only.

    The aliases are deterministic translations of German terms already present
    in the chunk. ``raw_text`` remains unchanged so citations stay verbatim.
    """

    if language.lower() != "de":
        return list(drafts)

    supported: list[ChunkDraft] = []
    for draft in drafts:
        aliases = _aliases_for_german_text(f"{draft.content}\n{draft.raw_text}")
        if not aliases:
            supported.append(draft)
            continue

        support_text = (
            "\n\nRetrieval support only; English aliases for German terms already present: "
            f"{', '.join(aliases)}."
        )
        supported.append(
            replace(
                draft,
                content=f"{draft.content}{support_text}",
                metadata={
                    **draft.metadata,
                    "retrieval_support_language": "en",
                    "retrieval_support_terms": list(aliases),
                },
            )
        )
    return supported


def _aliases_for_german_text(value: str) -> tuple[str, ...]:
    normalised = _normalise(value)
    aliases: list[str] = []
    seen: set[str] = set()

    for german_terms, english_aliases in _GERMAN_TERM_ALIASES:
        if not any(_contains_term(normalised, term) for term in german_terms):
            continue
        for alias in english_aliases:
            if alias in seen:
                continue
            aliases.append(alias)
            seen.add(alias)

    return tuple(aliases)


def _contains_term(normalised_text: str, term: str) -> bool:
    normalised_term = re.escape(_normalise(term))
    return bool(re.search(rf"(?<![a-z0-9]){normalised_term}(?![a-z0-9])", normalised_text))


def _normalise(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value.casefold())
    normalised = "".join(character for character in normalised if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", normalised))
