from __future__ import annotations

from io import BytesIO

import fitz

from app.rag.loaders import load_pdf_pages_with_tables


def test_load_pdf_pages_with_tables_extracts_grid_table_and_removes_it_from_prose() -> None:
    pdf_bytes = _make_pdf_with_grid_table()

    pages = load_pdf_pages_with_tables(pdf_bytes)

    assert len(pages) == 1
    page = pages[0]
    assert "Executive summary" in page.text
    assert "After table prose" in page.text
    assert "Submitted evidence" not in page.text
    assert "Site-level differences" not in page.text
    assert len(page.tables) == 1

    table = page.tables[0]
    assert table.title == "Evidence and Access Table"
    assert table.headers == [
        "Domain",
        "Submitted evidence",
        "Assessment concern",
        "Retrieval signal",
    ]
    assert table.rows[0] == {
        "Domain": "Clinical outcomes",
        "Submitted evidence": "Fewer readmissions",
        "Assessment concern": "Site-level differences",
        "Retrieval signal": "readmission uncertainty",
    }


def _make_pdf_with_grid_table() -> bytes:
    document = fitz.open()
    page = document.new_page(width=420, height=595)
    page.insert_text((48, 48), "Executive summary", fontsize=11)
    page.insert_text((48, 66), "This prose should remain available for normal chunking.", fontsize=9)
    page.insert_text((48, 120), "Evidence and Access Table", fontsize=11)

    x0, y0 = 48, 145
    column_widths = [76, 100, 100, 84]
    row_height = 34
    rows = [
        ["Domain", "Submitted evidence", "Assessment concern", "Retrieval signal"],
        [
            "Clinical outcomes",
            "Fewer readmissions",
            "Site-level differences",
            "readmission uncertainty",
        ],
    ]

    x_positions = [x0]
    for width in column_widths:
        x_positions.append(x_positions[-1] + width)
    y_positions = [y0 + row_height * index for index in range(len(rows) + 1)]

    for x in x_positions:
        page.draw_line((x, y_positions[0]), (x, y_positions[-1]), width=0.7)
    for y in y_positions:
        page.draw_line((x_positions[0], y), (x_positions[-1], y), width=0.7)

    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            page.insert_text(
                (x_positions[col_index] + 3, y_positions[row_index] + 14),
                cell,
                fontsize=6,
            )

    page.insert_text((48, 240), "After table prose", fontsize=11)
    page.insert_text((48, 258), "This paragraph should not be removed.", fontsize=9)

    buffer = BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()
