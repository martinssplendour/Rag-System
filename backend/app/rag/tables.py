from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StructuredTable:
    page_number: int | None
    table_index: int
    title: str | None
    headers: list[str]
    rows: list[dict[str, str]]
    bounding_box: tuple[float, float, float, float] | None = None


def table_row_text(
    *,
    document_title: str,
    table: StructuredTable,
    row: dict[str, str],
) -> str:
    lines = _table_context_lines(document_title, table)
    for header in table.headers:
        value = row.get(header)
        if header and value:
            lines.append(f"{header}: {value}.")
    return "\n".join(lines)


def whole_table_text(*, document_title: str, table: StructuredTable) -> str:
    lines = _table_context_lines(document_title, table)
    for row_index, row in enumerate(table.rows, start=1):
        lines.append(f"Row {row_index}:")
        for header in table.headers:
            value = row.get(header)
            if header and value:
                lines.append(f"{header}: {value}.")
    return "\n".join(lines)


def table_metadata(table: StructuredTable) -> dict[str, Any]:
    return {
        "table_title": table.title,
        "table_headers": table.headers,
        "table_rows": table.rows,
        "bounding_box": list(table.bounding_box) if table.bounding_box else None,
    }


def _table_context_lines(document_title: str, table: StructuredTable) -> list[str]:
    lines = [f"Table: {table.title or 'Detected table'}", f"Document: {document_title}"]
    if table.page_number is not None:
        lines.append(f"Page: {table.page_number}")
    lines.append("")
    return lines
