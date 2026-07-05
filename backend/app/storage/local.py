"""Local filesystem StorageProvider for the MVP and tests.

File writes use ``safe_join`` so a maliciously crafted document id/filename
can never escape the configured storage root (security checklist section 4,
path traversal).
"""

from __future__ import annotations

from pathlib import Path

from app.utils.files import safe_join


class LocalStorageProvider:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def put(self, path: str, data: bytes, content_type: str) -> str:
        full_path = Path(safe_join(self._base_dir, path))
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return str(full_path)

    async def read(self, path: str) -> bytes:
        full_path = Path(safe_join(self._base_dir, path))
        return full_path.read_bytes()

    async def delete(self, path: str) -> None:
        full_path = Path(safe_join(self._base_dir, path))
        if full_path.exists():
            full_path.unlink()
