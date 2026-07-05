"""Filesystem-safety helpers: filename sanitisation, extension checks, and
path-traversal-safe joining.

Security checklist references: section 4 (Path Traversal) and section 13
(file uploads validate extension and are stored outside any web-executable
root).
"""

from __future__ import annotations

import os
import re
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath

from app.core.constants import ALLOWED_EXTENSIONS

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 200


def sanitize_filename(filename: str) -> str:
    """Strip any directory components and unsafe characters from a filename.

    Never derive a storage path from a raw client-supplied filename without
    passing it through this first.
    """
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        name = "upload"
    name = _UNSAFE_CHARS.sub("_", name)
    return name[:_MAX_FILENAME_LENGTH] or "upload"


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def is_allowed_extension(filename: str) -> bool:
    return extension_of(filename) in ALLOWED_EXTENSIONS


_PDF_MAGIC_BYTES = b"%PDF-"


def looks_like_pdf(data: bytes) -> bool:
    """Verify actual file content, not just the claimed extension.

    Security checklist section 13: "File uploads validate both MIME type
    and actual file content (magic bytes), not just the extension." A
    `.pdf`-named upload containing arbitrary binary content must be
    rejected even though its extension is allowed.
    """
    return data.startswith(_PDF_MAGIC_BYTES)


def looks_like_utf8_text(data: bytes) -> bool:
    """Reject `.txt`-named uploads that are not actually decodable text
    (e.g. a renamed binary/executable). Plain text has no magic-byte
    signature, so a successful UTF-8 decode is the practical equivalent
    content check for this file type."""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def looks_like_docx(data: bytes) -> bool:
    """Validate a DOCX container without trusting the extension.

    DOCX files are ZIP archives with a fixed OpenXML structure. Requiring
    these entries rejects arbitrary ZIP/binary uploads renamed to `.docx`.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def safe_join(base_dir: str | Path, *parts: str) -> str:
    """Join ``parts`` under ``base_dir``, rejecting any path that would
    resolve outside ``base_dir`` (e.g. via ``..`` segments).
    """
    base = os.path.realpath(str(base_dir))
    candidate = os.path.realpath(os.path.join(base, *parts))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError("Resolved path escapes the allowed storage root")
    return candidate
