from app.rag.chunking import ChunkDraft
from app.rag.retrieval.lexical import tokenize_query_for_lexical
from app.rag.retrieval_support import add_english_retrieval_support


def test_german_retrieval_support_adds_english_aliases_without_changing_raw_text() -> None:
    raw_text = (
        "Zusätzliche Nachweise sollten längere Nachbeobachtung, "
        "Subgruppenanalysen, patientenrelevante Endpunkte und "
        "Real-World-Evidenz aus der Routineversorgung umfassen."
    )
    draft = ChunkDraft(
        content=f"Document: german.txt\n\n{raw_text}",
        raw_text=raw_text,
        section_title="Evidenzlücken",
        page_number=None,
        start_index=None,
    )

    supported = add_english_retrieval_support([draft], language="de")

    assert supported[0].raw_text == raw_text
    assert "additional evidence" in supported[0].content
    assert "longer follow-up" in supported[0].content
    assert "subgroup analyses" in supported[0].content
    assert "patient-relevant endpoints" in supported[0].content
    assert "real-world evidence" in supported[0].content
    assert supported[0].metadata["retrieval_support_language"] == "en"


def test_retrieval_support_does_not_change_non_german_chunks() -> None:
    draft = ChunkDraft(
        content="Document: uk.txt\n\nAdditional evidence was requested.",
        raw_text="Additional evidence was requested.",
        section_title=None,
        page_number=None,
        start_index=None,
    )

    supported = add_english_retrieval_support([draft], language="en")

    assert supported == [draft]


def test_additional_evidence_query_terms_are_kept_and_expanded() -> None:
    terms = tokenize_query_for_lexical(
        "What additional evidence would strengthen the German digital therapeutic dossier?"
    )

    assert "additional" in terms
    assert "zusatzliche" in terms
    assert "nachweise" in terms
    assert "starken" in terms
    assert "therapeutik" in terms
