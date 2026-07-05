"""Storage provider interface.

Swappable backend boundary: local filesystem for the MVP, Supabase private
Storage as the documented production replacement (see main build spec
section 16). Nothing outside this module and its implementations should
know which backend is active.
"""

from typing import Protocol


class StorageProvider(Protocol):
    async def put(self, path: str, data: bytes, content_type: str) -> str: ...

    async def read(self, path: str) -> bytes: ...

    async def delete(self, path: str) -> None: ...
