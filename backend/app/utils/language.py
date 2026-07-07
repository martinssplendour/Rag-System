"""Local language detection for uploaded evidence.

Explicit upload/header hints always win. Auto-detection is local-only via
Lingua when installed; the small keyword fallback keeps tests and local
development usable if the optional native package is unavailable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

SUPPORTED_LANGUAGE_CODES = {"en", "de", "fr", "it"}

_LANGUAGE_HINTS = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "de": "de",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "deutsch": "de",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "francais": "fr",
    "fran\u00e7ais": "fr",
    "it": "it",
    "ita": "it",
    "italian": "it",
    "italiano": "it",
}
_AUTO_HINTS = {"", "auto", "autodetect", "auto_detect", "auto-detect", "unknown"}
_GERMAN_MARKER_CHARS = set("\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc\u00df")
_FRENCH_MARKER_CHARS = set(
    "\u00e0\u00e2\u00e7\u00e8\u00e9\u00ea\u00eb"
    "\u00ee\u00ef\u00f4\u00f9\u00fb\u00fc\u00ff\u0153"
)
_ITALIAN_MARKER_CHARS = set("\u00e0\u00e8\u00e9\u00ec\u00ed\u00ee\u00f2\u00f3\u00f9\u00fa")
_MIN_LINGUA_CONFIDENCE = 0.35


def normalise_language_hint(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip().lower().replace(" ", "_")
    if normalised in _AUTO_HINTS:
        return None
    return _LANGUAGE_HINTS.get(normalised)


def detect_language(text: str, hint: str | None = None) -> str:
    explicit = normalise_language_hint(hint)
    if explicit:
        return explicit

    detected = _detect_with_lingua(text)
    if detected:
        return detected

    return _detect_with_fallback(text)


def _detect_with_lingua(text: str) -> str | None:
    try:
        detector, language_to_code = _lingua_detector()
    except ImportError:
        return None

    stripped = text.strip()
    if not stripped:
        return "unknown"

    confidence_values = detector.compute_language_confidence_values(stripped)
    if not confidence_values:
        return "unknown"

    best = max(confidence_values, key=lambda confidence: confidence.value)
    if best.value < _MIN_LINGUA_CONFIDENCE:
        return "unknown"
    return language_to_code.get(best.language, "unknown")


@lru_cache(maxsize=1)
def _lingua_detector() -> tuple[Any, dict[Any, str]]:
    from lingua import Language, LanguageDetectorBuilder

    languages = (
        Language.ENGLISH,
        Language.GERMAN,
        Language.FRENCH,
        Language.ITALIAN,
    )
    detector = LanguageDetectorBuilder.from_languages(*languages).build()
    return detector, {
        Language.ENGLISH: "en",
        Language.GERMAN: "de",
        Language.FRENCH: "fr",
        Language.ITALIAN: "it",
    }


def _detect_with_fallback(text: str) -> str:
    lowered = f" {text.lower()} "
    if any(ch in lowered for ch in _GERMAN_MARKER_CHARS) or _contains_any(
        lowered, (" der ", " die ", " das ", " und ", " nicht ", " nutzenbewertung ")
    ):
        return "de"
    if any(ch in lowered for ch in _FRENCH_MARKER_CHARS) or _contains_any(
        lowered, (" le ", " la ", " les ", " des ", " remboursement ", " evaluation ")
    ):
        return "fr"
    if any(ch in lowered for ch in _ITALIAN_MARKER_CHARS) or _contains_any(
        lowered, (" il ", " lo ", " gli ", " della ", " rimborso ", " valutazione ")
    ):
        return "it"
    return "en"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
