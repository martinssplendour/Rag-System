"""Document loading: turn raw bytes/text into LangChain ``Document`` objects.

PDF pages are read with column-major coordinate sorting rather than
PyMuPDF's raw stream order or a simple row-band sort. Both dataset PDFs use
a strict left-column/right-column body layout (verified against the real
France/Italy files' block coordinates): the left column runs from the
title down to the final section, and the right column is a second,
independent stream of sections starting at the top of the page. A
row-band sort interleaves the two columns mid-sentence; the correct order
is every left-column block top-to-bottom, then every right-column block
top-to-bottom. See BUILD_SPEC_PART1_INGESTION.md section 1 (reference:
main spec section 9.3).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import fitz
from docx import Document as DocxDocument
from langchain_core.documents import Document


def _column_major_sort_key(block: tuple, page_width: float) -> tuple[int, float]:
    x0, y0 = block[0], block[1]
    column = 0 if x0 < page_width / 2 else 1
    return (column, y0)


def _collapse_block_text(raw_block_text: str) -> str:
    """Join a block's internal word-wrap line breaks into a single line.

    PyMuPDF blocks contain "\\n" wherever the PDF layout engine wrapped a
    line, not wherever a real paragraph/heading boundary exists -- if left
    alone, a wrapped sentence fragment ending mid-clause can be mistaken
    for a section heading by split_into_sections. Collapsing here and
    joining blocks with a blank line (see load_pdf_pages) restores a
    paragraph-per-block structure that matches what the chunker expects.
    """
    return " ".join(raw_block_text.split())


def load_pdf_pages(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Extract per-page text in reading order.

    Returns a list of ``(page_number, text)`` with 1-based page numbers.
    Blocks are separated by a blank line so each becomes one
    ``split_into_sections`` paragraph.
    """
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages: list[tuple[int, str]] = []
        for zero_based_index, page in enumerate(document):
            blocks = page.get_text("blocks")
            ordered = sorted(blocks, key=lambda block: _column_major_sort_key(block, page.rect.width))
            collapsed = [_collapse_block_text(block[4]) for block in ordered]
            text = "\n\n".join(block_text for block_text in collapsed if block_text)
            pages.append((zero_based_index + 1, text))
        return pages
    finally:
        document.close()


def load_pdf(pdf_bytes: bytes, metadata: dict[str, Any]) -> list[Document]:
    return [
        Document(page_content=text, metadata={**metadata, "page_number": page_number})
        for page_number, text in load_pdf_pages(pdf_bytes)
    ]


def load_docx_text(docx_bytes: bytes) -> str:
    document = DocxDocument(BytesIO(docx_bytes))
    blocks: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            blocks.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))

    return "\n\n".join(blocks)


def load_docx(docx_bytes: bytes, metadata: dict[str, Any]) -> list[Document]:
    return [Document(page_content=load_docx_text(docx_bytes), metadata=metadata)]


def load_text(text: str, metadata: dict[str, Any]) -> list[Document]:
    return [Document(page_content=text, metadata=metadata)]
