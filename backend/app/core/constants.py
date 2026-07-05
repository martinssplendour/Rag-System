"""Fixed vocabulary shared across the ingestion pipeline.

Kept separate from config.py: these are not environment-tunable, they are
structural facts about the dataset and file formats this app understands.
"""

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
ALLOWED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

SOURCE_TYPE_TXT = "txt"
SOURCE_TYPE_PDF = "pdf"
SOURCE_TYPE_DOCX = "docx"
SOURCE_TYPE_DIRECT_TEXT = "direct_text"

STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

INGESTION_JOB_PENDING = "pending"
INGESTION_JOB_RUNNING = "running"
INGESTION_JOB_SUCCEEDED = "succeeded"
INGESTION_JOB_FAILED = "failed"

# Canonical metadata field -> recognised header label variants.
# The UK/English documents use the left-hand labels; the German document uses
# the same line-per-field header layout but with German labels. See
# BUILD_SPEC_PART1_INGESTION.md section 2.1 for why this exists.
HEADER_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "external_document_id": ("Document ID", "Dokument-ID"),
    "country": ("Country", "Land"),
    "therapy_area": ("Therapy area", "Therapiegebiet"),
    "technology_type": ("Technology type", "Technologietyp", "Technology"),
    "assessment_body": ("Assessment body", "Bewertungsumfeld"),
}

# Heading text (case-insensitive) that marks the start of a trailing
# "suggested test questions" section which must be excluded from indexed
# content. See BUILD_SPEC_PART1_INGESTION.md section 2.2.
TRAILER_HEADINGS: tuple[str, ...] = (
    "useful questions for testing retrieval",
    "useful retrieval questions",
    "nützliche fragen zum testen der retrieval-funktion",
)
