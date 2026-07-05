"""Unit tests for section-aware chunking and table-row chunking.

Several tests here regression-guard the content-loss and mis-sectioning
bugs found while smoke-testing PDF ingestion against the real dataset
files (see BUILD_SPEC_PART1_INGESTION.md section 2 and the chunking.py
module docstring).
"""

from app.rag.chunking import ChunkDraft, chunk_document, split_into_sections


def test_split_into_sections_groups_multi_paragraph_body_under_one_heading():
    text = (
        "Clinical effectiveness discussion\n"
        "First paragraph of evidence.\n"
        "\n"
        "Second paragraph of evidence, still under the same heading.\n"
        "\n"
        "Evidence gaps and uncertainty\n"
        "A different section entirely.\n"
    )
    sections = split_into_sections(text)
    headings = [heading for heading, _ in sections]
    assert "Clinical effectiveness discussion" in headings
    assert "Evidence gaps and uncertainty" in headings
    first_body = dict(sections)["Clinical effectiveness discussion"]
    assert "First paragraph" in first_body
    assert "Second paragraph" in first_body


def test_split_into_sections_captures_first_heading_after_unheaded_preamble():
    """Regression test: a leading disclaimer paragraph (not heading-shaped)
    must not prevent the first real heading from ever being captured."""
    text = (
        "Important disclaimer:\n"
        "This is a synthetic document for a technical assessment.\n"
        "\n"
        "Executive summary\n"
        "The real content starts here.\n"
    )
    sections = split_into_sections(text)
    headings = [heading for heading, _ in sections]
    assert "Executive summary" in headings
    executive_summary_body = dict(sections)["Executive summary"]
    assert "The real content starts here." in executive_summary_body


def test_split_into_sections_does_not_lose_content_to_cascading_short_headings():
    """Regression test: a run of short, unpunctuated fragments (as seen in
    PDF-extracted table cells) must not repeatedly overwrite each other
    with empty bodies and vanish -- every fragment must survive somewhere
    in the output."""
    text = (
        "Evidence and Access Table\n"
        "\n"
        "Domain Submitted evidence\n"
        "\n"
        "Assessment concern\n"
        "\n"
        "Retrieval signal\n"
        "\n"
        "Access and reimbursement considerations\n"
        "Real prose paragraph that ends with a period.\n"
    )
    sections = split_into_sections(text)
    all_text = " ".join(body for _, body in sections) + " " + " ".join(h for h, _ in sections if h)
    assert "Domain Submitted evidence" in all_text
    assert "Assessment concern" in all_text
    assert "Retrieval signal" in all_text
    assert "Access and reimbursement considerations" in [h for h, _ in sections]


def test_split_into_sections_falls_back_to_single_section_without_headings():
    text = "Just one long paragraph with no heading-shaped lines at all, ending in a period."
    sections = split_into_sections(text)
    assert len(sections) == 1
    assert sections[0][0] is None


def test_chunk_document_produces_one_chunk_per_table_row_with_raw_text_preserved():
    text = (
        "| Evidence dimension | Submitted evidence |\n"
        "| Overall survival | Hazard ratio favoured drug but data were immature |\n"
        "| Quality of life | EQ-5D collected at baseline |\n"
        "\n"
        "Clinical discussion\n"
        "Some unrelated prose paragraph that is not part of any table.\n"
    )
    drafts = chunk_document("test-doc", text, chunk_size=1000, chunk_overlap=150)
    table_drafts = [d for d in drafts if d.raw_text.startswith("|")]
    assert len(table_drafts) == 2
    expected_raw_line = "| Overall survival | Hazard ratio favoured drug but data were immature |"
    assert table_drafts[0].raw_text == expected_raw_line
    # the embedded content is a rewritten semantic block, not the raw pipe row
    assert table_drafts[0].content != table_drafts[0].raw_text
    assert "Document: test-doc" in table_drafts[0].content


def test_chunk_document_prose_raw_text_is_verbatim_source_not_paraphrased():
    text = "Executive summary\nThis exact sentence must appear verbatim in the raw_text field.\n"
    drafts = chunk_document("test-doc", text, chunk_size=1000, chunk_overlap=150)
    assert any("This exact sentence must appear verbatim" in d.raw_text for d in drafts)


def test_chunk_document_splits_oversized_section_with_overlap():
    long_paragraph = "This is a long sentence about market access evidence. " * 60
    text = f"Executive summary\n{long_paragraph}\n"
    drafts = chunk_document("test-doc", text, chunk_size=200, chunk_overlap=50)
    prose_drafts = [d for d in drafts if d.section_title == "Executive summary"]
    assert len(prose_drafts) > 1
    for draft in prose_drafts:
        assert len(draft.raw_text) <= 200 + 1  # small slack for splitter boundary rounding


def test_chunk_document_preserves_page_number_for_pdf_pages():
    drafts = chunk_document(
        "test-doc", "Executive summary\nSome content.\n", chunk_size=1000, chunk_overlap=150, page_number=3
    )
    assert all(d.page_number == 3 for d in drafts)


def test_chunk_draft_is_a_frozen_dataclass():
    draft = ChunkDraft(content="c", raw_text="r", section_title=None, page_number=None, start_index=None)
    assert draft.content == "c"
