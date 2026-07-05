"""API/integration tests for /health, POST /documents, GET /documents.

Uses the mock embedding provider exclusively -- no test here requires a
paid API key (see main build spec section 24.5).
"""

from __future__ import annotations

from io import BytesIO

import fitz
import pytest
from docx import Document as DocxDocument
from httpx import AsyncClient

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


async def test_duplicate_content_is_rejected_with_409(client: AsyncClient):
    content = b"Identical content for duplicate detection test."
    first = await client.post("/documents", files={"file": ("first.txt", content, "text/plain")})
    assert first.status_code == 202

    second = await client.post("/documents", files={"file": ("second.txt", content, "text/plain")})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_DOCUMENT"


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
