"""Seed the configured Postgres database + Chroma store with the four real candidate
dataset documents, going through the same document_service.create_document
path that POST /documents uses.

Explicit metadata (country/country_code/language) is supplied here rather
than relying purely on header parsing -- see
BUILD_SPEC_PART1_INGESTION.md section 2.1 and 3.6: header parsing is
best-effort enrichment only, this script is the authoritative source for
the four known documents.

Run from the repository root:

    python scripts/seed_dataset.py
"""

from __future__ import annotations

import asyncio
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DATASET_ZIP = REPO_ROOT / "kintiga_market_access_candidate_dataset.zip"

sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.constants import TRAILER_HEADINGS  # noqa: E402
from app.domain.errors import ServiceError  # noqa: E402
from app.domain.uploads import UploadedFileInput  # noqa: E402
from app.rag.embeddings import get_embedding_provider  # noqa: E402
from app.repositories.database import build_engine, build_session_factory, create_all  # noqa: E402
from app.services import document_service  # noqa: E402
from app.services.ingestion_worker import process_next_ingestion_job  # noqa: E402
from app.storage.local import LocalStorageProvider  # noqa: E402
from app.vectorstores.chroma_store import ChromaVectorStore, build_chroma_resources  # noqa: E402

# External document id -> (filename in zip, country, country_code, language)
# See main build spec section 8.3 (domain metadata table).
DATASET_FILES: list[tuple[str, str, str, str]] = [
    ("uk_nice_oncology_drug_summary.txt", "United Kingdom", "UK", "en"),
    ("germany_amnog_digital_therapeutic_note_de.txt", "Germany", "DE", "de"),
    ("france_has_medtech_reimbursement_summary.pdf", "France", "FR", "en"),
    ("italy_pricing_reimbursement_pathway_note.pdf", "Italy", "IT", "en"),
]

# Paths/files to ignore during seed import -- see main spec section 8.2.
_IGNORED_PREFIXES = ("__MACOSX/", "._")
_IGNORED_NAMES = {".DS_Store", "README_DATASET.md"}


def _read_dataset_file(filename: str) -> bytes:
    with zipfile.ZipFile(DATASET_ZIP) as archive:
        for name in archive.namelist():
            base_name = Path(name).name
            if base_name != filename:
                continue
            if any(part.startswith(_IGNORED_PREFIXES) for part in Path(name).parts):
                continue
            if base_name in _IGNORED_NAMES:
                continue
            return archive.read(name)
    raise FileNotFoundError(f"{filename!r} not found in {DATASET_ZIP}")


async def _seed_one(
    filename: str,
    country: str,
    country_code: str,
    language: str,
    *,
    session,
    workspace_id: str,
    storage,
    embedding_provider,
    vector_store,
    settings,
) -> None:
    content = _read_dataset_file(filename)
    upload_file = UploadedFileInput(filename=filename, content=content)

    try:
        document = await document_service.create_document(
            session=session,
            workspace_id=workspace_id,
            storage=storage,
            settings=settings,
            file=upload_file,
            text=None,
            title=None,
            country=country,
            country_code=country_code,
            language=language,
        )
    except ServiceError as exc:
        if exc.code == "DUPLICATE_DOCUMENT":
            print(f"  {filename}: already seeded, skipping ({exc.details})")
            return
        raise

    print(
        f"  {filename}: accepted for ingestion status={document.status} language={document.language}"
    )


async def _verify(session_factory) -> None:
    """Assert the dataset-specific ingestion checks for any SQL backend."""
    async with session_factory() as session:
        rows = (await session.execute(text("SELECT raw_text FROM document_chunks"))).fetchall()

    all_raw_text = " ".join(str(row[0]) for row in rows if row[0]).lower()
    for heading in TRAILER_HEADINGS:
        assert heading not in all_raw_text, f"trailer heading leaked into index: {heading!r}"

    umlaut_found = any("\u00fc" in str(row[0]).casefold() for row in rows if row[0])
    assert umlaut_found, "expected at least one chunk with a preserved German umlaut (u-umlaut)"

    print("\nVerification passed:")
    print("  - no trailer/test-question sections leaked into indexed content")
    print("  - German diacritics preserved in at least one chunk")


async def main() -> None:
    if not DATASET_ZIP.exists():
        raise SystemExit(f"Dataset zip not found at {DATASET_ZIP}")

    settings = get_settings()
    engine = build_engine(settings.database_url)
    await create_all(engine)
    session_factory = build_session_factory(engine)

    storage = LocalStorageProvider(settings.local_storage_dir)
    embedding_provider = get_embedding_provider(
        provider=settings.embedding_provider,
        openai_api_key=settings.openai_api_key,
        gemini_api_key=settings.gemini_api_key,
        model=settings.embedding_model,
    )
    chroma_resources = build_chroma_resources(
        settings.chroma_persist_dir,
        collection_name=settings.chroma_collection_name,
    )
    vector_store = ChromaVectorStore(chroma_resources.collection)

    print(f"Seeding from {DATASET_ZIP.name} (embedding provider: {settings.embedding_provider})")
    for filename, country, country_code, language in DATASET_FILES:
        async with session_factory() as session:
            await _seed_one(
                filename,
                country,
                country_code,
                language,
                session=session,
                workspace_id=settings.default_workspace_id,
                storage=storage,
                embedding_provider=embedding_provider,
                vector_store=vector_store,
                settings=settings,
            )
        while await process_next_ingestion_job(
            session_factory=session_factory,
            storage=storage,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            settings=settings,
        ):
            pass

    await _verify(session_factory)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
