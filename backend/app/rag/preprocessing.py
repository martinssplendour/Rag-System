"""Cleaning, header-metadata extraction, and table-row detection.

Cleaning is conservative by design: it never paraphrases prose. Table rows
are the one exception -- they get rewritten into a semantic block for
embedding, but the literal original row is always preserved separately as
``raw_text`` (see extract_table_rows / TableRow.raw_line) so citations stay
verbatim to the source document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.constants import HEADER_KEY_ALIASES, TRAILER_HEADINGS

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_LINE_FIELD_PATTERN = re.compile(r"^\s*([^:]{2,40}):\s*(.+?)\s*$")


def clean_whitespace(text: str) -> str:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    normalised = _TRAILING_WS.sub("\n", normalised)
    normalised = _MULTI_BLANK_LINES.sub("\n\n", normalised)
    return normalised.strip()


def strip_trailer_section(text: str) -> tuple[str, int]:
    """Remove a trailing "suggested test questions" section if present.

    See BUILD_SPEC_PART1_INGESTION.md section 2.2 -- every dataset document
    ends with a block of retrieval test questions that must never be
    indexed as if it were evidence.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip().lower() in TRAILER_HEADINGS:
            removed_text = "\n".join(lines[index:])
            kept_text = "\n".join(lines[:index]).rstrip()
            return kept_text, len(removed_text)
    return text, 0


def strip_header_block(text: str) -> tuple[str, int]:
    """Remove the leading "Key: Value" header block once its fields have
    already been captured by parse_header_metadata.

    Without this, the raw header lines (document id, country, therapy
    area, ...) get chunked as if they were prose, producing a nonsense
    chunk such as "Section: Technology type: Medicine" -- caught via a
    live smoke test against the real UK dataset file. Only strips a
    *leading, contiguous* run of field-shaped lines, so it is a no-op for
    the PDF documents (whose first line is a title, not a field line) and
    never removes real prose that merely contains a colon.
    """
    lines = text.split("\n")
    index = 0
    while index < len(lines) and _LINE_FIELD_PATTERN.match(lines[index]):
        index += 1
    if index == 0:
        return text, 0
    removed_text = "\n".join(lines[:index])
    kept_text = "\n".join(lines[index:]).lstrip("\n")
    return kept_text, len(removed_text)


def _build_label_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, labels in HEADER_KEY_ALIASES.items():
        for label in labels:
            lookup[label.strip().lower()] = canonical
    return lookup


_LABEL_LOOKUP = _build_label_lookup()


def parse_header_metadata(text: str) -> dict[str, str]:
    """Best-effort metadata extraction from a document's leading header.

    Handles the two header layouts in the dataset: one "Key: Value" pair
    per line (English or German labels), and a single pipe-separated line
    (the PDF documents). This is enrichment only -- callers must let
    explicit upload-time fields take precedence over whatever this returns.
    """
    result: dict[str, str] = {}

    for line in text.splitlines()[:15]:
        # Lines containing "|" belong to the PDF pipe-separated format and
        # must be handled by the pipe-aware pass below -- matching them
        # here directly would capture the trailing "|" as part of the
        # value (e.g. "france_has_medtech_reimbursement_summary |") and
        # pre-empt the pipe-aware pass via the early return below.
        if "|" in line:
            continue
        match = _LINE_FIELD_PATTERN.match(line)
        if not match:
            continue
        canonical = _LABEL_LOOKUP.get(match.group(1).strip().lower())
        if canonical and canonical not in result:
            result[canonical] = match.group(2).strip()

    if result:
        return result

    # PDF header fields sometimes wrap across two physical lines (e.g.
    # "Document ID: ... |" then "Country: ... | Technology: ..."). Only
    # combine the lines that actually carry "|" fields, joined with a
    # space rather than a newline -- joining arbitrary raw lines before
    # splitting on "|" lets the single-line regex's negated character
    # class span the embedded newline and match unpredictably.
    pipe_lines = [line for line in text.splitlines()[:15] if "|" in line]
    combined = " ".join(pipe_lines)
    for segment in combined.split("|"):
        match = _LINE_FIELD_PATTERN.match(segment.strip())
        if not match:
            continue
        canonical = _LABEL_LOOKUP.get(match.group(1).strip().lower())
        if canonical and canonical not in result:
            result[canonical] = match.group(2).strip()

    return result


@dataclass(frozen=True)
class TableRow:
    section_title: str | None
    headers: list[str]
    values: list[str]
    raw_line: str


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 3


def extract_table_rows(text: str) -> tuple[list[TableRow], str]:
    """Detect pipe-delimited tables and split them into individual rows.

    Returns the detected rows plus the input text with every consumed
    table line removed, so downstream prose chunking never re-splits the
    raw table text. PDF-extracted text never contains literal ``|``
    delimiters, so this is a no-op (zero rows) for PDF pages by
    construction -- see the PDF table-handling note in
    BUILD_SPEC_PART1_INGESTION.md.
    """
    lines = text.split("\n")
    rows: list[TableRow] = []
    remaining_lines: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not _is_table_line(line):
            remaining_lines.append(line)
            index += 1
            continue

        section_title = next((prior.strip() for prior in reversed(remaining_lines) if prior.strip()), None)
        header_cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        index += 1

        while index < len(lines) and _is_table_line(lines[index]):
            data_line = lines[index]
            value_cells = [cell.strip() for cell in data_line.strip().strip("|").split("|")]
            rows.append(
                TableRow(
                    section_title=section_title,
                    headers=header_cells,
                    values=value_cells,
                    raw_line=data_line.strip(),
                )
            )
            index += 1

    cleaned_text = _MULTI_BLANK_LINES.sub("\n\n", "\n".join(remaining_lines)).strip()
    return rows, cleaned_text


def build_row_semantic_block(document_title: str, row: TableRow) -> str:
    """Rewrite a table row into a self-describing block for embedding.

    This is the one place ingestion is allowed to paraphrase evidence text
    (see module docstring) -- it exists purely to make the row searchable
    in isolation; ``row.raw_line`` remains the citable original.
    """
    lines = [f"Document: {document_title}"]
    if row.section_title:
        lines.append(f"Section: {row.section_title}")
    for header, value in zip(row.headers, row.values, strict=False):
        if header and value:
            lines.append(f"{header}: {value}.")
    return "\n".join(lines)
