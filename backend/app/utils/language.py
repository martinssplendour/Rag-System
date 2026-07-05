"""Minimal language detection.

Only two languages appear in the candidate dataset (English and German), so
a full language-detection library would be overkill. Explicit hints (from
an upload field or parsed document header) always win; the character-based
heuristic is a last-resort fallback only.
"""

_GERMAN_MARKER_CHARS = set("äöüÄÖÜß")


def detect_language(text: str, hint: str | None = None) -> str:
    if hint:
        return hint.strip().lower()
    if any(ch in _GERMAN_MARKER_CHARS for ch in text):
        return "de"
    return "en"
