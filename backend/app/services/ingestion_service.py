"""Ingestion pipeline: load -> extract header metadata -> clean -> chunk ->
embed -> persist (Postgres metadata + Chroma vectors).

Runs after document_service has already created the ``documents`` row and
stored the original file/text -- this module only turns that content into
searchable chunks. See BUILD_SPEC_PART1_INGESTION.md section 9 and the
interface contract in section 3 (what Part 2 depends on).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.constants import SOURCE_TYPE_DOCX, SOURCE_TYPE_PDF
from app.rag.chunking import ChunkDraft, chunk_document, chunk_structured_table
from app.rag.embeddings import EmbeddingProvider
from app.rag.loaders import load_docx_text, load_pdf_pages_with_tables
from app.rag.preprocessing import (
    clean_whitespace,
    parse_header_metadata,
    strip_header_block,
    strip_trailer_section,
)
from app.repositories.chunks import ChunkRepository
from app.repositories.models import DocumentChunk
from app.utils.language import detect_language
from app.vectorstores.base import VectorStore


@dataclass(frozen=True)
class LoadedSourcePage:
    page_number: int | None
    text: str
    tables: list


@dataclass(frozen=True)
class DocumentContext:
    document_id: str
    workspace_id: str
    title: str
    source_type: str
    external_document_id: str | None
    citation_prefix: str | None
    country: str | None
    country_code: str | None


@dataclass(frozen=True)
class IngestionResult:
    extracted_metadata: dict[str, str]
    chunk_count: int


def _load_pages(
    *, source_type: str, text: str | None, pdf_bytes: bytes | None, docx_bytes: bytes | None
) -> list[LoadedSourcePage]:
    if source_type == SOURCE_TYPE_PDF:
        if pdf_bytes is None:
            raise ValueError("pdf_bytes is required for source_type='pdf'")
        return [
            LoadedSourcePage(page.page_number, page.text, page.tables)
            for page in load_pdf_pages_with_tables(pdf_bytes)
        ]
    if source_type == SOURCE_TYPE_DOCX:
        if docx_bytes is None:
            raise ValueError("docx_bytes is required for source_type='docx'")
        return [LoadedSourcePage(None, load_docx_text(docx_bytes), [])]
    if text is None:
        raise ValueError("text is required for text source types")
    return [LoadedSourcePage(None, text, [])]


def _draft_chunks(
    pages: list[LoadedSourcePage],
    *,
    context: DocumentContext,
    chunk_size: int,
    chunk_overlap: int,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page in pages:
        cleaned = clean_whitespace(page.text)
        cleaned, _removed_header_chars = strip_header_block(cleaned)
        cleaned, _removed_trailer_chars = strip_trailer_section(cleaned)
        drafts.extend(
            chunk_document(
                context.title,
                cleaned,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                page_number=page.page_number,
            )
        )
        for table in page.tables:
            drafts.extend(
                chunk_structured_table(
                    context.title,
                    table,
                    table_id=_table_id(context, page.page_number, table.table_index),
                )
            )
    return drafts


def _build_chunk_row(
    draft: ChunkDraft, *, index: int, context: DocumentContext, language: str
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4().hex,
        workspace_id=context.workspace_id,
        document_id=context.document_id,
        chunk_index=index,
        content=draft.content,
        raw_text=draft.raw_text,
        section_title=draft.section_title,
        page_number=draft.page_number,
        start_index=draft.start_index,
        language=language,
        token_count=len(draft.content.split()),
        chunk_metadata=draft.metadata,
    )


def _build_vector_payload(
    chunk_id: str,
    draft: ChunkDraft,
    embedding: list[float],
    *,
    index: int,
    context: DocumentContext,
    language: str,
    effective_country: str | None,
    effective_external_document_id: str | None,
    embedding_model_name: str,
) -> dict:
    return {
        "id": chunk_id,
        "embedding": embedding,
        "document_text": draft.content,
        "metadata": {
            "workspace_id": context.workspace_id,
            "document_id": context.document_id,
            "external_document_id": effective_external_document_id or "",
            "citation_prefix": context.citation_prefix or "",
            "title": context.title,
            "country": effective_country or "",
            "country_code": context.country_code or "",
            "language": language,
            "section_title": draft.section_title or "",
            "page_number": draft.page_number if draft.page_number is not None else -1,
            "chunk_index": index,
            "status": "ready",
            "source_type": context.source_type,
            "embedding_model": embedding_model_name,
            "raw_text": draft.raw_text,
            **_flatten_chunk_metadata(draft.metadata),
        },
    }


def _flatten_chunk_metadata(metadata: dict) -> dict[str, str | int | float | bool]:
    flattened: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            flattened[key] = value
        else:
            flattened[key] = json.dumps(value, ensure_ascii=False)
    return flattened


def _table_id(context: DocumentContext, page_number: int | None, table_index: int) -> str:
    source = context.external_document_id or context.title or context.document_id
    slug = Path(str(source)).stem.lower()
    slug = "".join(ch if ch.isalnum() else "_" for ch in slug).strip("_") or "document"
    page_label = page_number if page_number is not None else 1
    return f"{slug}-p{page_label}-t{table_index}"


async def ingest_document(
    context: DocumentContext,
    *,
    text: str | None,
    pdf_bytes: bytes | None,
    docx_bytes: bytes | None,
    language_hint: str | None,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    chunk_repo: ChunkRepository,
    embedding_model_name: str,
    chunk_size: int,
    chunk_overlap: int,
) -> IngestionResult:
    pages = _load_pages(
        source_type=context.source_type, text=text, pdf_bytes=pdf_bytes, docx_bytes=docx_bytes
    )
    extracted_metadata = parse_header_metadata(pages[0].text) if pages else {}

    drafts = _draft_chunks(
        pages,
        context=context,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    full_text = "\n".join(page.text for page in pages)
    language = detect_language(full_text, hint=language_hint or extracted_metadata.get("language"))
    extracted_metadata["language"] = language

    effective_country = context.country or extracted_metadata.get("country")
    effective_external_id = context.external_document_id or extracted_metadata.get("external_document_id")

    if drafts:
        embeddings = await embedding_provider.embed_documents([draft.content for draft in drafts])
        chunk_rows: list[DocumentChunk] = []
        vector_payload: list[dict] = []
        for index, (draft, embedding) in enumerate(zip(drafts, embeddings, strict=True)):
            row = _build_chunk_row(draft, index=index, context=context, language=language)
            chunk_rows.append(row)
            vector_payload.append(
                _build_vector_payload(
                    row.id,
                    draft,
                    embedding,
                    index=index,
                    context=context,
                    language=language,
                    effective_country=effective_country,
                    effective_external_document_id=effective_external_id,
                    embedding_model_name=embedding_model_name,
                )
            )
        await chunk_repo.bulk_create(chunk_rows)
        vector_store.upsert_chunks(vector_payload)

    return IngestionResult(extracted_metadata=extracted_metadata, chunk_count=len(drafts))
