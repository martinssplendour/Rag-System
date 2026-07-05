"""Turn cleaned document text into chunk drafts ready for embedding.

Table rows (see preprocessing.extract_table_rows) become one chunk per row.
Everything else is split into heading-delimited sections first, then
recursively split by size only if a section exceeds the target chunk size.
A prose chunk's ``raw_text`` is the literal source text (identical to what
gets embedded, minus the prepended document/section header) -- prose is
never paraphrased, unlike table rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.preprocessing import TableRow, build_row_semantic_block, extract_table_rows


@dataclass(frozen=True)
class ChunkDraft:
    content: str
    raw_text: str
    section_title: str | None
    page_number: int | None
    start_index: int | None


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    return stripped[-1] not in ".!?:,;"


def split_into_sections(text: str) -> list[tuple[str | None, str]]:
    """Best-effort split of prose into (heading, body) sections.

    A line is treated as a heading when it is short, has no terminal
    punctuation, and sits on a blank-line/start-of-document boundary.
    Tuned to this dataset's short sentence-case section titles (e.g.
    "Executive summary", "Evidenzübersicht"). Deliberately does not require
    the *next* line to be non-blank: PDF pages (see loaders.py) join every
    block with a blank-line separator, heading block included, so a
    next-line-non-blank check would never match a real PDF heading. Text
    that matches no heading falls back to a single unnamed section --
    content is never dropped, only left unlabelled.
    """
    lines = text.split("\n")
    raw_sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_body: list[str] = []

    def body_has_content() -> bool:
        return any(body_line.strip() for body_line in current_body)

    def just_set_heading_without_body() -> bool:
        # True only in the narrow window right after a heading was
        # captured and before any body line has accumulated under it.
        return current_heading is not None and not body_has_content()

    for line in lines:
        # A heading-shaped line always starts a new section (including
        # replacing an unlabelled `None` preamble heading once it has
        # gathered body content, e.g. a leading disclaimer paragraph
        # before the first real "Executive summary" heading) -- UNLESS we
        # just captured a heading and nothing has been added to its body
        # yet. That guard stops a run of short, unpunctuated fragments
        # (e.g. PDF table cells like "Domain Submitted evidence",
        # "Retrieval signal") from each overwriting the previous
        # still-empty heading and silently discarding the whole table once
        # empty-body sections are filtered below. Caught via live
        # ingestion smoke tests against the real dataset files.
        if _looks_like_heading(line) and not just_set_heading_without_body():
            raw_sections.append((current_heading, current_body))
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)
    raw_sections.append((current_heading, current_body))

    result = [(heading, "\n".join(body).strip()) for heading, body in raw_sections]
    result = [(heading, body) for heading, body in result if body]
    return result or [(None, text.strip())]


def _chunk_prose(
    document_title: str,
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    page_number: int | None,
) -> list[ChunkDraft]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True
    )
    drafts: list[ChunkDraft] = []
    for heading, body in split_into_sections(text):
        if len(body) <= chunk_size:
            pieces: list[tuple[str, int | None]] = [(body, 0)]
        else:
            docs = splitter.create_documents([body])
            pieces = [(doc.page_content, doc.metadata.get("start_index")) for doc in docs]

        for piece_text, start_index in pieces:
            prefix = f"Document: {document_title}\n"
            prefix += f"Section: {heading}\n\n" if heading else "\n"
            drafts.append(
                ChunkDraft(
                    content=prefix + piece_text,
                    raw_text=piece_text,
                    section_title=heading,
                    page_number=page_number,
                    start_index=start_index,
                )
            )
    return drafts


def _chunk_table_rows(
    document_title: str, rows: list[TableRow], *, page_number: int | None
) -> list[ChunkDraft]:
    return [
        ChunkDraft(
            content=build_row_semantic_block(document_title, row),
            raw_text=row.raw_line,
            section_title=row.section_title,
            page_number=page_number,
            start_index=None,
        )
        for row in rows
    ]


def chunk_document(
    document_title: str,
    cleaned_text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    page_number: int | None = None,
) -> list[ChunkDraft]:
    """Chunk one page/section of cleaned text.

    Works unmodified for both TXT documents (which may contain
    pipe-delimited tables) and PDF pages (which never contain literal
    ``|`` table delimiters after extraction, so table-row detection is a
    natural no-op and everything flows through prose chunking).
    """
    rows, remaining_text = extract_table_rows(cleaned_text)
    drafts = _chunk_table_rows(document_title, rows, page_number=page_number)
    if remaining_text.strip():
        drafts += _chunk_prose(
            document_title,
            remaining_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            page_number=page_number,
        )
    return drafts
