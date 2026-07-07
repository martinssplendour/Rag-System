from __future__ import annotations

import hashlib
import re

COUNTRY_CODES_BY_NAME = {
    "uk": "UK",
    "gb": "UK",
    "gbr": "UK",
    "great britain": "UK",
    "united kingdom": "UK",
    "england": "UK",
    "france": "FR",
    "fr": "FR",
    "germany": "DE",
    "deutschland": "DE",
    "de": "DE",
    "italy": "IT",
    "italia": "IT",
    "it": "IT",
}

DOCUMENT_CODE_PRIORITY = {
    "nice": "NICE",
    "has": "HAS",
    "amnog": "AMNOG",
    "aifa": "AIFA",
    "gba": "GBA",
    "g-ba": "GBA",
    "pricing": "PRICING",
}

DOCUMENT_STOP_WORDS = {
    "access",
    "assessment",
    "connected",
    "country",
    "device",
    "digital",
    "doc",
    "document",
    "drug",
    "evidence",
    "france",
    "germany",
    "italy",
    "medicine",
    "medtech",
    "note",
    "oncology",
    "pathway",
    "pricing",
    "reimbursement",
    "summary",
    "therapeutic",
    "uk",
}


def build_document_citation_base(
    *,
    country: str | None,
    country_code: str | None,
    document_identity: str,
) -> str:
    country_segment = stable_country_code(country=country, country_code=country_code)
    document_segment = stable_document_code(document_identity)
    return f"{country_segment}-{document_segment}"


def allocate_document_citation_prefix(base: str, existing_prefixes: set[str]) -> str:
    if base not in existing_prefixes:
        return base
    for sequence in range(2, 1000):
        candidate = f"{base}-{sequence:02d}"
        if candidate not in existing_prefixes:
            return candidate
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6].upper()
    return f"{base}-{digest}"


def build_chunk_source_id(
    *,
    citation_prefix: str,
    chunk_index: int | None,
    chunk_id: str,
) -> str:
    return f"{citation_prefix}-{stable_chunk_number(chunk_index=chunk_index, chunk_id=chunk_id):03d}"


def stable_country_code(*, country: str | None, country_code: str | None) -> str:
    for candidate in [country_code, country]:
        if not candidate:
            continue
        normalised = normalise_words(candidate)
        mapped = COUNTRY_CODES_BY_NAME.get(normalised)
        if mapped:
            return mapped
        compact = re.sub(r"[^A-Za-z]", "", candidate).upper()
        if len(compact) >= 2:
            return compact[:2]
    return "XX"


def stable_document_code(identity: str) -> str:
    lower_identity = identity.lower()
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", lower_identity)

    for token, code in DOCUMENT_CODE_PRIORITY.items():
        if token in tokens or token in lower_identity:
            return code

    for token in tokens:
        if token in DOCUMENT_STOP_WORDS:
            continue
        if len(token) < 3:
            continue
        return normalise_label_segment(token)

    fallback = re.sub(r"[^A-Za-z0-9]", "", identity).upper()
    return fallback[:12] or "DOC"


def stable_chunk_number(*, chunk_index: int | None, chunk_id: str) -> int:
    if chunk_index is not None and chunk_index >= 0:
        return chunk_index + 1
    digest = hashlib.sha1(chunk_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 999 + 1


def normalise_words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def normalise_label_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return segment[:12] or "DOC"
