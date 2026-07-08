from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadedFileInput:
    filename: str | None
    content: bytes
