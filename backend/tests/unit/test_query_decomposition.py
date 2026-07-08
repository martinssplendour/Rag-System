from __future__ import annotations

from app.rag.query_decomposition import decompose_question


def test_decompose_question_splits_one_question_per_line() -> None:
    question = """
    What were the UK evidence gaps?
    Why was the survival evidence uncertain?
    """

    assert decompose_question(question) == [
        "What were the UK evidence gaps?",
        "Why was the survival evidence uncertain?",
    ]


def test_decompose_question_splits_numbered_and_bulleted_lists() -> None:
    question = """
    1. What concerns were raised about the comparator?
    - What evidence would strengthen the dossier?
    """

    assert decompose_question(question) == [
        "What concerns were raised about the comparator?",
        "What evidence would strengthen the dossier?",
    ]


def test_decompose_question_splits_multiple_question_marks_and_dash_paste() -> None:
    question = (
        "What kind of managed entry agreement was proposed? - "
        "Why was the Italian budget impact estimate uncertain? - "
        "Which documents mention registry collection?"
    )

    assert decompose_question(question) == [
        "What kind of managed entry agreement was proposed?",
        "Why was the Italian budget impact estimate uncertain?",
        "Which documents mention registry collection?",
    ]


def test_decompose_question_splits_spaced_dash_only_when_parts_are_questions() -> None:
    question = "Explain the UK evidence gaps - Compare the German comparator concerns"

    assert decompose_question(question) == [
        "Explain the UK evidence gaps",
        "Compare the German comparator concerns",
    ]


def test_decompose_question_does_not_split_normal_hyphenated_terms() -> None:
    question = "How does market-access evidence support cost-effectiveness?"

    assert decompose_question(question) == [
        "How does market-access evidence support cost-effectiveness?"
    ]
