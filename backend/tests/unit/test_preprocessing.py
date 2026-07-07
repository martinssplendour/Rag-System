"""Unit tests for cleaning, header metadata extraction, trailer/header
stripping, and table-row detection.

Several of these tests exist specifically to regression-guard defects
found while smoke-testing ingestion against the real dataset files (see
BUILD_SPEC_PART1_INGESTION.md section 2).
"""

from app.rag.preprocessing import (
    build_row_semantic_block,
    clean_whitespace,
    extract_table_rows,
    parse_header_metadata,
    strip_header_block,
    strip_trailer_section,
)


def test_clean_whitespace_normalises_line_endings_and_blank_lines():
    raw = "line one\r\nline two\r\n\n\n\nline three   \n"
    cleaned = clean_whitespace(raw)
    assert "\r" not in cleaned
    assert "\n\n\n" not in cleaned
    assert "line three   " not in cleaned  # trailing spaces stripped


def test_clean_whitespace_removes_null_characters():
    assert "\x00" not in clean_whitespace("hello\x00world")


def test_parse_header_metadata_english_line_per_field():
    text = (
        "Synthetic Document: UK NICE Oncology Drug Summary\n"
        "Document ID: uk_nice_oncology_drug_summary\n"
        "Country: United Kingdom\n"
        "Language: English\n"
        "Therapy area: Oncology\n"
        "Technology type: Medicine\n"
        "Assessment body: NICE-style health technology evaluation\n"
    )
    result = parse_header_metadata(text)
    assert result["external_document_id"] == "uk_nice_oncology_drug_summary"
    assert result["country"] == "United Kingdom"
    assert result["language"] == "English"
    assert result["therapy_area"] == "Oncology"
    assert result["technology_type"] == "Medicine"


def test_parse_header_metadata_german_line_per_field():
    """Regression test: the German document uses German header labels
    (Land, Dokument-ID, ...) with the same line-per-field layout as the
    English files. A parser that only recognises English labels silently
    drops these fields -- see BUILD_SPEC_PART1_INGESTION.md section 2.1."""
    text = (
        "Synthetisches Dokument: Deutschland AMNOG-Notiz\n"
        "Dokument-ID: germany_amnog_digital_therapeutic_note_de\n"
        "Land: Deutschland\n"
        "Therapiegebiet: Management chronischer Erkrankungen\n"
        "Technologietyp: Digitale Therapeutik\n"
        "Bewertungsumfeld: G-BA / IQWiG\n"
    )
    result = parse_header_metadata(text)
    assert result["external_document_id"] == "germany_amnog_digital_therapeutic_note_de"
    assert result["country"] == "Deutschland"
    assert result["therapy_area"] == "Management chronischer Erkrankungen"


def test_parse_header_metadata_pdf_pipe_separated_format():
    text = (
        "France HAS-Style MedTech\n"
        "Reimbursement Summary\n"
        "Document ID: france_has_medtech_reimbursement_summary |\n"
        "Country: France | Technology: Connected medical device\n"
    )
    result = parse_header_metadata(text)
    assert result["external_document_id"] == "france_has_medtech_reimbursement_summary"
    assert result["country"] == "France"
    assert result["technology_type"] == "Connected medical device"


def test_strip_trailer_section_removes_english_variant():
    text = "Real evidence here.\n\nUseful questions for testing retrieval\n1. What evidence gaps?\n"
    kept, removed_chars = strip_trailer_section(text)
    assert "Useful questions" not in kept
    assert "What evidence gaps" not in kept
    assert removed_chars > 0
    assert "Real evidence here." in kept


def test_strip_trailer_section_removes_german_variant():
    text = "Echte Evidenz hier.\n\nNützliche Fragen zum Testen der Retrieval-Funktion\n1. Frage?\n"
    kept, _ = strip_trailer_section(text)
    assert "Nützliche Fragen" not in kept
    assert "Echte Evidenz hier." in kept


def test_strip_trailer_section_is_noop_without_trailer():
    text = "Just regular prose with no trailer section."
    kept, removed_chars = strip_trailer_section(text)
    assert kept == text
    assert removed_chars == 0


def test_strip_header_block_removes_leading_field_lines():
    """Regression test: without stripping, the raw header block gets
    chunked as prose, producing a nonsense chunk like
    'Section: Technology type: Medicine' -- see
    BUILD_SPEC_PART1_INGESTION.md section 2, defect 1."""
    text = (
        "Document ID: uk_nice_oncology_drug_summary\n"
        "Country: United Kingdom\n"
        "Technology type: Medicine\n"
        "\n"
        "Important disclaimer:\n"
        "This is a synthetic document.\n"
    )
    kept, removed_chars = strip_header_block(text)
    assert "Document ID:" not in kept
    assert "Technology type:" not in kept
    assert "Important disclaimer:" in kept
    assert removed_chars > 0


def test_strip_header_block_is_noop_when_first_line_is_not_a_field():
    """PDF documents lead with a title line, not a field line -- stripping
    must not touch them."""
    text = "France HAS-Style MedTech\nReimbursement Summary\nExecutive summary\nSome prose.\n"
    kept, removed_chars = strip_header_block(text)
    assert kept == text
    assert removed_chars == 0


def test_extract_table_rows_parses_pipe_delimited_table():
    text = (
        "Key evidence table\n"
        "| Evidence dimension | Submitted evidence | Committee concern | Retrieval signal |\n"
        "| Overall survival | Hazard ratio favoured drug | Crossover uncertainty | immature OS |\n"
        "| Quality of life | EQ-5D collected | Missing data | HRQoL gap |\n"
        "\n"
        "Clinical effectiveness discussion\n"
        "Some prose after the table.\n"
    )
    rows, remaining_text = extract_table_rows(text)
    assert len(rows) == 2
    assert rows[0].section_title == "Key evidence table"
    expected_raw_line = (
        "| Overall survival | Hazard ratio favoured drug | Crossover uncertainty | immature OS |"
    )
    assert rows[0].raw_line == expected_raw_line
    assert "|" not in remaining_text
    assert "Clinical effectiveness discussion" in remaining_text
    assert "Some prose after the table." in remaining_text


def test_extract_table_rows_returns_empty_for_pdf_style_text():
    """PDF-extracted text never contains literal pipe delimiters -- this
    must be a safe no-op, not an error."""
    text = "Domain Submitted evidence\nClinical outcomes Six-month controlled study\n"
    rows, remaining_text = extract_table_rows(text)
    assert rows == []
    assert remaining_text == text.strip()


def test_build_row_semantic_block_includes_document_title_and_cells():
    rows, _ = extract_table_rows(
        "| Evidence dimension | Submitted evidence |\n| Overall survival | Immature data |\n"
    )
    block = build_row_semantic_block("uk_nice_oncology_drug_summary.txt", rows[0])
    assert "Document: uk_nice_oncology_drug_summary.txt" in block
    assert "Evidence dimension: Overall survival." in block
    assert "Submitted evidence: Immature data." in block
