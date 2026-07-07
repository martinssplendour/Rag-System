"""Tests for local language normalisation and auto-detection."""

from app.utils.language import detect_language, normalise_language_hint


def test_normalise_language_hint_accepts_codes_and_names():
    assert normalise_language_hint("en") == "en"
    assert normalise_language_hint("English") == "en"
    assert normalise_language_hint("Deutsch") == "de"
    assert normalise_language_hint("French") == "fr"
    assert normalise_language_hint("Italiano") == "it"


def test_normalise_language_hint_treats_auto_as_missing():
    assert normalise_language_hint(None) is None
    assert normalise_language_hint("auto") is None
    assert normalise_language_hint("Auto detect") is None
    assert normalise_language_hint("unknown") is None


def test_detect_language_uses_explicit_hint_first():
    assert detect_language("Der Text looks mixed.", hint="English") == "en"


def test_detect_language_detects_supported_languages():
    assert detect_language("The reimbursement evidence describes clinical outcomes.") == "en"
    assert detect_language("Der Gemeinsame Bundesausschuss pr\u00fcft den Zusatznutzen.") == "de"
    assert detect_language("Le remboursement depend de l'evaluation clinique.") == "fr"
    assert detect_language("Il rimborso dipende dalla valutazione clinica.") == "it"
