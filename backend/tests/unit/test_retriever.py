from __future__ import annotations

import pytest

from app.rag.retriever import (
    ChromaRetriever,
    RetrievedChunk,
    assign_source_labels,
    distance_to_similarity,
    select_final_chunks,
)


def test_select_final_chunks_filters_threshold_and_caps_per_document() -> None:
    chunks = [
        _chunk("1", "doc-a", 0.91, "alpha evidence"),
        _chunk("2", "doc-a", 0.90, "beta evidence"),
        _chunk("3", "doc-a", 0.89, "gamma evidence"),
        _chunk("4", "doc-b", 0.88, "delta evidence"),
        _chunk("5", "doc-c", 0.30, "weak evidence"),
    ]

    selected = select_final_chunks(
        chunks,
        min_similarity=0.45,
        limit=4,
        max_chunks_per_document=2,
    )

    assert [chunk.chunk_id for chunk in selected] == ["1", "2", "4"]


def test_select_final_chunks_keeps_single_document_context_beyond_diversity_cap() -> None:
    chunks = [
        _chunk("1", "doc-a", 0.91, "alpha evidence"),
        _chunk("2", "doc-a", 0.90, "beta evidence"),
        _chunk("3", "doc-a", 0.89, "gamma evidence"),
        _chunk("4", "doc-a", 0.88, "delta evidence"),
    ]

    selected = select_final_chunks(
        chunks,
        min_similarity=0.45,
        limit=4,
        max_chunks_per_document=2,
    )

    assert [chunk.chunk_id for chunk in selected] == ["1", "2", "3", "4"]


def test_select_final_chunks_removes_near_duplicate_text() -> None:
    chunks = [
        _chunk("1", "doc-a", 0.91, "same evidence text"),
        _chunk("2", "doc-b", 0.90, "same evidence text"),
        _chunk("3", "doc-c", 0.89, "different evidence text"),
    ]

    selected = select_final_chunks(
        chunks,
        min_similarity=0.45,
        limit=5,
        max_chunks_per_document=3,
    )

    assert [chunk.chunk_id for chunk in selected] == ["1", "3"]


def test_assign_source_labels_are_globally_stable() -> None:
    chunks = [
        _chunk(
            "abc",
            "doc-a",
            0.80,
            "first",
            external_document_id="uk_nice_oncology_drug_summary",
            country="United Kingdom",
            country_code="UK",
            chunk_index=0,
        ),
        _chunk(
            "def",
            "doc-b",
            0.79,
            "second",
            external_document_id="france_has_medtech_reimbursement_summary",
            country="France",
            country_code="FR",
            chunk_index=2,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [(source.source_id, source.chunk.chunk_id) for source in labeled] == [
        ("UK-NICE-001", "abc"),
        ("FR-HAS-003", "def"),
    ]


def test_assign_source_labels_uses_document_code_priorities() -> None:
    chunks = [
        _chunk(
            "de",
            "doc-de",
            0.80,
            "first",
            external_document_id="germany_amnog_digital_therapeutic_note_de",
            country="Deutschland",
            chunk_index=12,
        ),
        _chunk(
            "it",
            "doc-it",
            0.79,
            "second",
            external_document_id="italy_pricing_reimbursement_pathway_note",
            country="Italy",
            chunk_index=0,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [source.source_id for source in labeled] == [
        "DE-AMNOG-013",
        "IT-PRICING-001",
    ]


def test_assign_source_labels_prefers_stored_citation_prefix() -> None:
    chunks = [
        _chunk(
            "abc",
            "doc-a",
            0.80,
            "first",
            external_document_id="uk_nice_oncology_drug_summary",
            citation_prefix="UK-NICE",
            country="United Kingdom",
            chunk_index=0,
        ),
        _chunk(
            "def",
            "doc-b",
            0.79,
            "second",
            external_document_id="uk_nice_second_oncology_summary",
            citation_prefix="UK-NICE-02",
            country="United Kingdom",
            chunk_index=0,
        ),
    ]

    labeled = assign_source_labels(chunks)

    assert [source.source_id for source in labeled] == [
        "UK-NICE-001",
        "UK-NICE-02-001",
    ]


def test_distance_to_similarity_is_bounded() -> None:
    assert distance_to_similarity(0.2) == 0.8
    assert distance_to_similarity(-1.0) == 1.0
    assert distance_to_similarity(2.0) == 0.0
    assert distance_to_similarity(None) == 0.0


@pytest.mark.anyio
async def test_retriever_falls_back_for_exact_table_keyword_match() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="budget-row",
                document_id="italy-doc",
                country="Italy",
                raw_text=(
                    "Table: Evidence and access. Domain: Population size. "
                    "Submitted evidence: Eligible population estimated from regional claims. "
                    "Negotiation concern: Regional coding variation and specialist referral "
                    "pathways may alter budget impact. Retrieval signal: budget impact."
                ),
                chunk_type="table_row",
            ),
            _chroma_row(
                chunk_id="implementation-row",
                document_id="italy-doc",
                country="Italy",
                raw_text=(
                    "Table: Evidence and access. Domain: Implementation. "
                    "Hospital-only prescribing through specialist centres."
                ),
                chunk_type="table_row",
            ),
        ],
        semantic_distances=[0.82, 0.86],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="Why was the Italian budget impact estimate uncertain?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="Italy",
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["budget-row"]
    assert chunks[0].metadata["lexical_score"] > 0


@pytest.mark.anyio
async def test_retriever_falls_back_for_privacy_table_row() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="privacy-row",
                document_id="france-doc",
                country="France",
                raw_text=(
                    "Table: Evidence and access. Domain: Data governance. "
                    "Submitted evidence: Manufacturer described EEA hosting and role-based access. "
                    "Assessment concern: Retention and audit logging needed clarification. "
                    "Retrieval signal: privacy concern."
                ),
                chunk_type="table_row",
            ),
            _chroma_row(
                chunk_id="workload-row",
                document_id="france-doc",
                country="France",
                raw_text=(
                    "Table: Evidence and access. Domain: Service delivery. "
                    "Clinician workload and alert accuracy required further evidence."
                ),
                chunk_type="table_row",
            ),
        ],
        semantic_distances=[0.86, 0.88],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What data privacy concerns were noted for the French connected device?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="France",
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["privacy-row"]


@pytest.mark.anyio
async def test_retriever_falls_back_for_managed_entry_agreement_table_row() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="managed-entry-row",
                document_id="italy-doc",
                country="Italy",
                raw_text=(
                    "Table: Evidence and access. Domain: Managed access. "
                    "Submitted evidence: Outcome-linked agreement with registry follow-up proposed. "
                    "Negotiation concern: Definitions of response and renewal need clarity. "
                    "Retrieval signal: MEA registry."
                ),
                chunk_type="table_row",
            ),
            _chroma_row(
                chunk_id="budget-row",
                document_id="italy-doc",
                country="Italy",
                raw_text=(
                    "Table: Evidence and access. Domain: Population size. "
                    "Regional coding variation may alter budget impact."
                ),
                chunk_type="table_row",
            ),
        ],
        semantic_distances=[0.86, 0.88],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What kind of managed entry agreement was proposed in the Italy note?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="Italy",
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["managed-entry-row"]


@pytest.mark.anyio
async def test_retriever_falls_back_for_german_dossier_name_question() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="german-dossier",
                document_id="germany-doc",
                country="Germany",
                raw_text=(
                    "The German digital therapeutic dossier assessed GlucoGuide-DTx. "
                    "The AMNOG note evaluated how the technology complements diabetes support."
                ),
                chunk_type="paragraph",
            ),
            _chroma_row(
                chunk_id="italy-note",
                document_id="italy-doc",
                country="Italy",
                raw_text="The Italy pricing note assessed NeuroMab-IT.",
                chunk_type="paragraph",
            ),
        ],
        semantic_distances=[0.87, 0.88],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What is the name of the German dossier?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country=None,
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["german-dossier"]


@pytest.mark.anyio
async def test_retriever_expands_english_query_for_german_hba1c_durability() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="hba1c-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text=(
                    "Evidenzübersicht. Bereich: Klinischer Endpunkt. "
                    "Eingereichte Evidenz: HbA1c-Reduktion nach 24 Wochen. "
                    "Bewertungsbedenken: Langfristige Dauerhaftigkeit über 24 Wochen "
                    "hinaus unklar. Retrieval-Signal: Evidenzlücke zur Dauerhaftigkeit."
                ),
                chunk_type="table_row",
            ),
            _chroma_row(
                chunk_id="population-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text="Die Studienpopulation wies eine hohe digitale Kompetenz auf.",
                chunk_type="paragraph",
            ),
        ],
        semantic_distances=[0.88, 0.86],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What was uncertain about the HbA1c benefit for GlucoGuide-DTx?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="Germany",
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["hba1c-row"]


@pytest.mark.anyio
async def test_retriever_expands_english_query_for_german_generalisability() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="generalisability-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text=(
                    "Zudem schloss die Studie Patienten mit eingeschränktem "
                    "Smartphone-Zugang, schwerer Komorbidität oder geringer digitaler "
                    "Kompetenz aus. Dadurch bestehen Unsicherheiten hinsichtlich "
                    "Gleichbehandlung, Zugangsgerechtigkeit und Generalisierbarkeit."
                ),
                chunk_type="paragraph",
            ),
            _chroma_row(
                chunk_id="hba1c-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text="HbA1c-Reduktion nach 24 Wochen; Dauerhaftigkeit unklar.",
                chunk_type="paragraph",
            ),
        ],
        semantic_distances=[0.88, 0.86],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="Why was generalisability of the German digital therapeutic evidence uncertain?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="Germany",
        document_ids=None,
        candidate_count=12,
    )

    assert chunks[0].chunk_id == "generalisability-row"


@pytest.mark.anyio
async def test_retriever_expands_english_query_for_german_payer_cost_concern() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="payer-cost-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text=(
                    "Akteure der gesetzlichen Krankenversicherung könnten Nachweise "
                    "verlangen, dass die digitale Therapeutik nicht lediglich zusätzliche "
                    "Kosten oberhalb bestehender Disease-Management-Programme verursacht. "
                    "Die Preisverhandlung würde auch Ressourcennutzung betreffen."
                ),
                chunk_type="paragraph",
            ),
            _chroma_row(
                chunk_id="usability-row",
                document_id="germany-doc",
                country="Germany",
                language="de",
                raw_text="Usability und App-Nutzung nahmen im Studienverlauf ab.",
                chunk_type="paragraph",
            ),
        ],
        semantic_distances=[0.88, 0.86],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What cost concern might German sickness-fund stakeholders raise about GlucoGuide-DTx?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="Germany",
        document_ids=None,
        candidate_count=12,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["payer-cost-row"]


@pytest.mark.anyio
async def test_retriever_does_not_lower_threshold_for_weak_keyword_overlap() -> None:
    collection = FakeCollection(
        [
            _chroma_row(
                chunk_id="generic-row",
                document_id="france-doc",
                country="France",
                raw_text="The uploaded evidence file contains a short market access summary.",
                chunk_type="paragraph",
            ),
        ],
        semantic_distances=[0.84],
    )
    retriever = ChromaRetriever(
        collection,
        min_similarity=0.75,
        final_context_count=2,
        max_chunks_per_document=3,
    )

    chunks = await retriever.retrieve(
        query="What evidence is available?",
        query_embedding=[0.1, 0.2],
        workspace_id="workspace",
        country="France",
        document_ids=None,
        candidate_count=12,
    )

    assert chunks == []


def _chunk(
    chunk_id: str,
    document_id: str,
    relevance_score: float,
    raw_text: str,
    external_document_id: str | None = None,
    citation_prefix: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    chunk_index: int | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        external_document_id=external_document_id,
        citation_prefix=citation_prefix,
        content=raw_text,
        raw_text=raw_text,
        title="Doc",
        country=country,
        country_code=country_code,
        chunk_index=chunk_index,
        relevance_score=relevance_score,
        metadata={"workspace_id": "workspace", "status": "ready"},
    )


def _chroma_row(
    *,
    chunk_id: str,
    document_id: str,
    country: str,
    raw_text: str,
    chunk_type: str,
    language: str = "en",
) -> dict[str, object]:
    return {
        "id": chunk_id,
        "document": raw_text,
        "metadata": {
            "workspace_id": "workspace",
            "status": "ready",
            "document_id": document_id,
            "external_document_id": document_id,
            "title": f"{country} evidence document",
            "country": country,
            "country_code": country[:2].upper(),
            "language": language,
            "chunk_index": 0,
            "chunk_type": chunk_type,
            "raw_text": raw_text,
            "table_id": f"{document_id}-table-1" if chunk_type.startswith("table") else "",
        },
    }


class FakeCollection:
    def __init__(
        self,
        rows: list[dict[str, object]],
        semantic_distances: list[float],
    ) -> None:
        self.rows = rows
        self.semantic_distances = semantic_distances

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, object],
        include: list[str],
    ) -> dict[str, object]:
        del query_embeddings, where, include
        rows = self.rows[:n_results]
        return {
            "ids": [[row["id"] for row in rows]],
            "documents": [[row["document"] for row in rows]],
            "metadatas": [[row["metadata"] for row in rows]],
            "distances": [self.semantic_distances[:n_results]],
        }

    def get(
        self,
        where: dict[str, object],
        include: list[str],
        limit: int,
    ) -> dict[str, object]:
        del where, include
        rows = self.rows[:limit]
        return {
            "ids": [row["id"] for row in rows],
            "documents": [row["document"] for row in rows],
            "metadatas": [row["metadata"] for row in rows],
        }
