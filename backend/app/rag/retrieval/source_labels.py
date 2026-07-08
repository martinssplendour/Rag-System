from __future__ import annotations

from collections.abc import Sequence

from app.rag.citation_labels import build_chunk_source_id, build_document_citation_base
from app.rag.retrieval.models import LabeledChunk, RetrievedChunk
from app.rag.retrieval.utils import optional_int, optional_str


def assign_source_labels(chunks: Sequence[RetrievedChunk]) -> list[LabeledChunk]:
    return [
        LabeledChunk(source_id=_stable_source_id(chunk), chunk=chunk)
        for chunk in chunks
    ]


def _stable_source_id(chunk: RetrievedChunk) -> str:
    prefix = chunk.citation_prefix or optional_str(chunk.metadata.get("citation_prefix"))
    if not prefix:
        prefix = build_document_citation_base(
            country=chunk.country or optional_str(chunk.metadata.get("country")),
            country_code=chunk.country_code or optional_str(chunk.metadata.get("country_code")),
            document_identity=" ".join(
                value
                for value in [
                    chunk.external_document_id,
                    optional_str(chunk.metadata.get("external_document_id")),
                    chunk.title,
                    chunk.document_id,
                ]
                if value
            ),
        )
    chunk_index = chunk.chunk_index
    if chunk_index is None:
        chunk_index = optional_int(chunk.metadata.get("chunk_index"))
    return build_chunk_source_id(
        citation_prefix=prefix,
        chunk_index=chunk_index,
        chunk_id=chunk.chunk_id,
    )
