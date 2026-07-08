"""Document creation/listing use case.

Owns validation, duplicate detection, original-file storage, and durable
ingestion-job creation. Route handlers
(app/api/routes/documents.py) call only this module and stay thin -- see
the senior-project-pack modularity checklist, layer boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import (
    SOURCE_TYPE_DIRECT_TEXT,
    SOURCE_TYPE_DOCX,
    SOURCE_TYPE_PDF,
    SOURCE_TYPE_TXT,
    STATUS_PROCESSING,
)
from app.domain.errors import ServiceError
from app.domain.uploads import UploadedFileInput
from app.rag.citation_labels import allocate_document_citation_prefix, build_document_citation_base
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_jobs import IngestionJobRepository
from app.repositories.models import Document
from app.storage.base import StorageProvider
from app.utils.files import (
    extension_of,
    is_allowed_extension,
    looks_like_docx,
    looks_like_pdf,
    looks_like_utf8_text,
    sanitize_filename,
)
from app.utils.hashing import sha256_hex
from app.utils.language import normalise_language_hint


@dataclass(frozen=True)
class UploadInput:
    raw_bytes: bytes
    source_type: str
    filename: str | None
    content_hash: str
    content_type: str


def _validate_file_upload(file: UploadedFileInput, settings: Settings) -> UploadInput:
    raw_bytes = file.content
    if len(raw_bytes) == 0:
        raise ServiceError("INVALID_INPUT", "Uploaded file is empty.", 400)
    if len(raw_bytes) > settings.max_upload_bytes:
        raise ServiceError("FILE_TOO_LARGE", "Uploaded file exceeds the maximum allowed size.", 413)
    safe_name = sanitize_filename(file.filename or "upload")
    if not is_allowed_extension(safe_name):
        raise ServiceError("UNSUPPORTED_FILE_TYPE", "Only PDF, TXT, and DOCX files are supported.", 415)

    extension = extension_of(safe_name)
    if extension == ".pdf":
        source_type = SOURCE_TYPE_PDF
        content_type = "application/pdf"
        content_is_valid = looks_like_pdf(raw_bytes)
    elif extension == ".docx":
        source_type = SOURCE_TYPE_DOCX
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        content_is_valid = looks_like_docx(raw_bytes)
    else:
        source_type = SOURCE_TYPE_TXT
        content_type = "text/plain"
        content_is_valid = looks_like_utf8_text(raw_bytes)

    # Validate actual content, not just the claimed extension (security
    # checklist section 13) -- a file named "report.pdf" containing
    # arbitrary binary content, or "notes.txt" containing a renamed
    # executable, must be rejected even though the extension is allowed.
    if not content_is_valid:
        raise ServiceError(
            "UNSUPPORTED_FILE_TYPE", "File content does not match its extension.", 415
        )
    return UploadInput(
        raw_bytes=raw_bytes,
        source_type=source_type,
        filename=safe_name,
        content_hash=sha256_hex(raw_bytes),
        content_type=content_type,
    )


def _validate_direct_text(text: str, title: str | None, settings: Settings) -> UploadInput:
    if not title or not title.strip():
        raise ServiceError("INVALID_INPUT", "title is required when submitting direct text.", 400)
    if len(text) == 0:
        raise ServiceError("INVALID_INPUT", "Direct text must not be empty.", 400)
    if len(text) > settings.max_direct_text_chars:
        raise ServiceError("INVALID_INPUT", "Direct text exceeds the maximum allowed length.", 400)
    raw_bytes = text.encode("utf-8")
    return UploadInput(
        raw_bytes=raw_bytes,
        source_type=SOURCE_TYPE_DIRECT_TEXT,
        filename=None,
        content_hash=sha256_hex(raw_bytes),
        content_type="text/plain",
    )


async def _resolve_upload(
    *, file: UploadedFileInput | None, text: str | None, title: str | None, settings: Settings
) -> UploadInput:
    if (file is None) == (text is None):
        raise ServiceError("INVALID_INPUT", "Exactly one of file or text must be supplied.", 400)
    if file is not None:
        return _validate_file_upload(file, settings)
    assert text is not None
    return _validate_direct_text(text, title, settings)


def _slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "document"


def _resolve_country_code(country: str | None, country_code: str | None) -> str | None:
    if country_code and country_code.strip():
        return country_code.strip().upper()
    if not country:
        return None
    return {
        "united kingdom": "UK",
        "uk": "UK",
        "great britain": "UK",
        "france": "FR",
        "germany": "DE",
        "deutschland": "DE",
        "italy": "IT",
        "italia": "IT",
    }.get(country.strip().lower())


def _external_document_id(upload: UploadInput, title: str | None, document_id: str) -> str:
    return Path(upload.filename).stem if upload.filename else _slugify(title or document_id)


async def _allocate_citation_prefix(
    *,
    doc_repo: DocumentRepository,
    workspace_id: str,
    country: str | None,
    country_code: str | None,
    document_identity: str,
) -> str:
    base = build_document_citation_base(
        country=country,
        country_code=country_code,
        document_identity=document_identity,
    )
    existing_prefixes = await _existing_citation_prefixes(doc_repo, workspace_id)
    return allocate_document_citation_prefix(base, existing_prefixes)


async def _existing_citation_prefixes(
    doc_repo: DocumentRepository,
    workspace_id: str,
) -> set[str]:
    documents = await doc_repo.list_for_citation_prefix_allocation(workspace_id)
    prefixes: set[str] = set()
    for document in documents:
        if document.citation_prefix:
            prefixes.add(document.citation_prefix)
            continue
        prefixes.add(
            build_document_citation_base(
                country=document.country,
                country_code=document.country_code,
                document_identity=" ".join(
                    value
                    for value in [
                        document.external_document_id,
                        document.title,
                        document.filename,
                        document.id,
                    ]
                    if value
                ),
            )
        )
    return prefixes


def _build_document_row(
    *,
    workspace_id: str,
    upload: UploadInput,
    title: str | None,
    country: str | None,
    country_code: str | None,
    language: str | None,
    therapy_area: str | None,
    technology_type: str | None,
    assessment_body: str | None,
    citation_prefix: str,
) -> Document:
    document_id = uuid4().hex
    external_document_id = _external_document_id(upload, title, document_id)
    resolved_title = title or upload.filename or "Untitled document"
    return Document(
        id=document_id,
        workspace_id=workspace_id,
        external_document_id=external_document_id,
        citation_prefix=citation_prefix,
        title=resolved_title,
        filename=upload.filename,
        country=country,
        country_code=_resolve_country_code(country, country_code),
        language=normalise_language_hint(language) or "unknown",
        therapy_area=therapy_area,
        technology_type=technology_type,
        assessment_body=assessment_body,
        source_type=upload.source_type,
        storage_path=None,
        content_hash=upload.content_hash,
        status=STATUS_PROCESSING,
        chunk_count=0,
    )


async def create_document(
    *,
    session: AsyncSession,
    workspace_id: str,
    storage: StorageProvider,
    settings: Settings,
    file: UploadedFileInput | None,
    text: str | None,
    title: str | None,
    country: str | None = None,
    country_code: str | None = None,
    language: str | None = None,
    therapy_area: str | None = None,
    technology_type: str | None = None,
    assessment_body: str | None = None,
) -> Document:
    upload = await _resolve_upload(file=file, text=text, title=title, settings=settings)

    doc_repo = DocumentRepository(session)
    existing = await doc_repo.get_by_hash(workspace_id, upload.content_hash)
    if existing is not None:
        raise ServiceError(
            "DUPLICATE_DOCUMENT",
            "A document with identical content already exists.",
            409,
            details={"document_id": existing.id},
        )

    document_id_seed = uuid4().hex
    external_document_id = _external_document_id(upload, title, document_id_seed)
    resolved_country_code = _resolve_country_code(country, country_code)
    citation_prefix = await _allocate_citation_prefix(
        doc_repo=doc_repo,
        workspace_id=workspace_id,
        country=country,
        country_code=resolved_country_code,
        document_identity=" ".join(
            value for value in [external_document_id, title, upload.filename] if value
        ),
    )

    document = await doc_repo.create(
        _build_document_row(
            workspace_id=workspace_id,
            upload=upload,
            title=title,
            country=country,
            country_code=resolved_country_code,
            language=language,
            therapy_area=therapy_area,
            technology_type=technology_type,
            assessment_body=assessment_body,
            citation_prefix=citation_prefix,
        )
    )

    storage_key = f"{workspace_id}/{document.id}/{upload.filename or 'direct_text.txt'}"
    document.storage_path = await storage.put(storage_key, upload.raw_bytes, upload.content_type)
    await session.flush()

    await IngestionJobRepository(session).create(
        workspace_id=workspace_id,
        document_id=document.id,
    )
    await session.commit()
    return document


async def list_documents(*, session: AsyncSession, workspace_id: str) -> list[Document]:
    return await DocumentRepository(session).list_all(workspace_id)
