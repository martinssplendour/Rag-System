"""API/integration tests for /health, POST /documents, GET /documents.

Uses the mock embedding provider exclusively -- no test here requires a
paid API key (see main build spec section 24.5).
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
import pytest
from docx import Document as DocxDocument
from httpx import AsyncClient
from sqlalchemy import text

from app.repositories.database import build_engine

pytestmark = pytest.mark.asyncio


def _make_pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _make_docx_bytes(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def test_health_returns_ok(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_ready_checks_dependencies(client: AsyncClient):
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_upload_txt_document_succeeds(client: AsyncClient, wait_for_document_status):
    content = (
        b"Document ID: sample_doc\nCountry: United Kingdom\n\n"
        b"Executive summary\nThis is the evidence body for the sample document.\n"
    )
    response = await client.post(
        "/documents",
        files={"file": ("sample_doc.txt", content, "text/plain")},
        data={"country": "United Kingdom"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["chunk_count"] == 0
    assert body["external_document_id"] == "sample_doc"

    ready = await wait_for_document_status(client, body["document_id"])
    assert ready["status"] == "ready"
    assert ready["chunk_count"] > 0
    assert ready["external_document_id"] == "sample_doc"


async def test_upload_pdf_document_succeeds(client: AsyncClient, wait_for_document_status):
    pdf_bytes = _make_pdf_bytes("Executive summary. This is a PDF evidence document about market access.")
    response = await client.post(
        "/documents",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        data={"country": "France"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["chunk_count"] == 0

    ready = await wait_for_document_status(client, body["document_id"])
    assert ready["status"] == "ready"
    assert ready["chunk_count"] > 0


async def test_upload_docx_document_succeeds(client: AsyncClient, wait_for_document_status):
    docx_bytes = _make_docx_bytes(
        "Document ID: word_doc_001",
        "Country: United Kingdom",
        "Executive summary",
        "This Word evidence document describes a market access evidence gap.",
    )
    response = await client.post(
        "/documents",
        files={
            "file": (
                "word_evidence.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"country": "United Kingdom"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["chunk_count"] == 0
    assert body["external_document_id"] == "word_evidence"

    ready = await wait_for_document_status(client, body["document_id"])
    assert ready["status"] == "ready"
    assert ready["chunk_count"] > 0
    assert ready["external_document_id"] == "word_evidence"


async def test_direct_text_ingestion_succeeds(client: AsyncClient, wait_for_document_status):
    response = await client.post(
        "/documents",
        data={
            "text": "This is direct text evidence about a market access topic.",
            "title": "Direct Text Doc",
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["title"] == "Direct Text Doc"
    assert body["filename"] is None
    assert body["status"] == "processing"
    ready = await wait_for_document_status(client, body["document_id"])
    assert ready["status"] == "ready"
    assert ready["chunk_count"] > 0


async def test_direct_text_without_title_is_rejected(client: AsyncClient):
    response = await client.post("/documents", data={"text": "Some evidence text without a title."})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_unsupported_file_extension_is_rejected(client: AsyncClient):
    response = await client.post(
        "/documents",
        files={"file": ("malware.exe", b"not a real document", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_pdf_extension_with_non_pdf_content_is_rejected(client: AsyncClient):
    """Security checklist section 13: content must be validated, not just
    the extension -- a .pdf-named file with arbitrary binary content must
    be rejected even though its extension is allowed."""
    response = await client.post(
        "/documents",
        files={"file": ("fake.pdf", b"this is not really a PDF file", "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_txt_extension_with_binary_content_is_rejected(client: AsyncClient):
    non_utf8_binary = b"\xff\xfe\x00\x01\x02\xfd\xfc"
    response = await client.post(
        "/documents",
        files={"file": ("fake.txt", non_utf8_binary, "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_docx_extension_with_non_docx_content_is_rejected(client: AsyncClient):
    response = await client.post(
        "/documents",
        files={
            "file": (
                "fake.docx",
                b"this is not really a Word document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_file_and_text_together_is_rejected(client: AsyncClient):
    response = await client.post(
        "/documents",
        files={"file": ("doc.txt", b"file content", "text/plain")},
        data={"text": "also direct text", "title": "Conflicting Doc"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_neither_file_nor_text_is_rejected(client: AsyncClient):
    response = await client.post("/documents", data={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_empty_file_is_rejected(client: AsyncClient):
    response = await client.post(
        "/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_oversized_file_is_rejected(client: AsyncClient):
    content = b"a" * 10_485_761
    response = await client.post(
        "/documents",
        files={"file": ("too-large.txt", content, "text/plain")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_duplicate_content_is_rejected_with_409(client: AsyncClient):
    content = b"Identical content for duplicate detection test."
    first = await client.post("/documents", files={"file": ("first.txt", content, "text/plain")})
    assert first.status_code == 202

    second = await client.post("/documents", files={"file": ("second.txt", content, "text/plain")})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_DOCUMENT"


async def test_admin_delete_soft_deletes_then_cleans_document_data(
    client: AsyncClient,
    postgres_database_url: str,
    wait_for_document_status,
):
    content = (
        b"Document ID: delete_me\nCountry: United Kingdom\n\n"
        b"Executive summary\nThis evidence should be removed after deletion.\n"
    )
    upload = await client.post(
        "/documents",
        files={"file": ("delete_me.txt", content, "text/plain")},
        data={"country": "United Kingdom"},
    )
    assert upload.status_code == 202
    document_id = upload.json()["document_id"]
    await wait_for_document_status(client, document_id)

    before = await _fetch_document_cleanup_state(postgres_database_url, document_id)
    assert before["status"] == "ready"
    assert before["chunk_count"] > 0
    assert await _count_chunks(postgres_database_url, document_id) > 0
    storage_path = before["storage_path"]
    assert storage_path
    assert Path(str(storage_path)).exists()

    delete_response = await client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 202
    assert delete_response.json() == {"document_id": document_id, "status": "deleted"}

    list_response = await client.get("/documents")
    assert list_response.status_code == 200
    assert document_id not in {
        item["document_id"] for item in list_response.json()["items"]
    }

    await _wait_for_deleted_cleanup(postgres_database_url, document_id)
    assert not Path(str(storage_path)).exists()

    reupload = await client.post(
        "/documents",
        files={"file": ("delete_me_again.txt", content, "text/plain")},
        data={"country": "United Kingdom"},
    )
    assert reupload.status_code == 202


async def test_list_documents_returns_uploaded_documents(client: AsyncClient):
    await client.post(
        "/documents",
        files={"file": ("listed_doc.txt", b"Some evidence content for the list test.", "text/plain")},
    )
    response = await client.get("/documents")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["filename"] == "listed_doc.txt" for item in body["items"])


async def test_list_documents_empty_initially(client: AsyncClient):
    response = await client.get("/documents")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_openapi_docs_are_served(client: AsyncClient):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "/documents" in response.json()["paths"]
    assert "/health" in response.json()["paths"]


async def _fetch_document_cleanup_state(database_url: str, document_id: str) -> dict[str, Any]:
    engine = build_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    select status, chunk_count, storage_path, content_hash
                    from documents
                    where id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            row = result.mappings().one()
            return dict(row)
    finally:
        await engine.dispose()


async def _count_chunks(database_url: str, document_id: str) -> int:
    engine = build_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("select count(*) from document_chunks where document_id = :document_id"),
                {"document_id": document_id},
            )
            return int(result.scalar_one() or 0)
    finally:
        await engine.dispose()


async def _wait_for_deleted_cleanup(database_url: str, document_id: str) -> None:
    for _ in range(40):
        state = await _fetch_document_cleanup_state(database_url, document_id)
        chunks = await _count_chunks(database_url, document_id)
        if state["status"] == "deleted" and state["storage_path"] is None and chunks == 0:
            return
        await asyncio.sleep(0.05)
    state = await _fetch_document_cleanup_state(database_url, document_id)
    chunks = await _count_chunks(database_url, document_id)
    raise AssertionError(f"cleanup did not finish; state={state!r} chunks={chunks}")
