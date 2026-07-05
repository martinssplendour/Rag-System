"""Vector store interface.

Chroma is the local MVP implementation; a Supabase/pgvector implementation
is the documented production replacement (main build spec section 15/29)
and would satisfy this same interface.
"""

from typing import Any, Protocol


class VectorStore(Protocol):
    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None: ...

    def delete_by_document(self, document_id: str) -> None: ...
