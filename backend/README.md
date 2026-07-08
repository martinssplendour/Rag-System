# Market Access Evidence Assistant — Backend

FastAPI backend for the Market Access Evidence Assistant. It handles auth, document upload,
background ingestion, retrieval, and grounded answer generation.

## What this covers

- `GET /health`, `GET /health/ready`
- `POST /auth/register`, `POST /auth/login` — real accounts, JWT-based auth (see Authentication below)
- `POST /documents` — upload `.txt`/`.pdf`, or submit direct text; returns `202 Accepted`
  with `status="processing"`
- `GET /documents` — list ingested documents and their status
- `POST /ask` — grounded question answering over ingested documents (Part 2)
- Background ingestion pipeline: load stored original → extract header metadata → clean →
  chunk (table-row-aware) → embed → persist (Postgres metadata + Chroma vectors) → mark
  `ready`/`failed`
- English retrieval support for German documents: deterministic English aliases are appended to
  searchable chunk `content` only, while `raw_text` stays unchanged for citations.
- SQLAlchemy-backed answer history for `questions`, `answers`, and `answer_sources`
- Swagger/OpenAPI at `/docs`, raw schema at `/openapi.json`

## Prerequisites

- Python 3.11+
- Postgres for app metadata.
- Chroma for vector search.
- The root Docker Compose app starts Postgres automatically.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
cp .env.example .env
```

## Running the API

For split local development, run Postgres in Docker from the repository root:

```bash
npm run db:dev
```

This recreates only the Postgres container with `localhost:5433` exposed and keeps the dev database
in the `postgres-dev-data` Docker volume.

Then use this value in `backend/.env`:

```text
DATABASE_URL=postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga
```

If you changed `POSTGRES_PASSWORD` in the root `.env`, use that same password in `DATABASE_URL`.
Then start the API from `backend/`:

```bash
uvicorn app.main:app --reload --port 8000
```

- Health check: `http://localhost:8000/health`
- Readiness check: `http://localhost:8000/health/ready`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

For direct backend runs, `DATABASE_URL` must point at Postgres. Chroma data and uploaded files are
written to `./data/` unless overridden. The root Docker Compose app starts Postgres and stores
uploaded files/Chroma data in Docker volumes.

`POST /documents` validates and stores the uploaded content, creates a durable `ingestion_jobs`
row, and returns quickly with the document in `processing` status. The in-process background worker
started by FastAPI then performs parsing, chunking, embedding, and Chroma upsert. `GET /documents`
is the status source of truth.

`DELETE /documents/{document_id}` is admin-only. It marks the document `deleted` first, then
background cleanup removes Chroma vectors, chunks, ingestion jobs, stored files, and retrieval cache
entries.

Uploads are checked for size, extension, and actual file content. In JWT mode, uploads are
admin-only. If background ingestion fails, the worker retries up to `INGESTION_JOB_MAX_ATTEMPTS`
before marking the document `failed`; stack traces stay in server logs and users only receive safe
status/error messages.

The upload UI keeps metadata deliberately small: country is selected from a controlled list, and
language is either selected (`en`, `de`, `fr`, `it`) or left for local auto-detection during
background ingestion. Internal repository fields still leave room for richer metadata later, but
the public upload workflow stays focused on the two fields that affect retrieval.

## Seeding the real dataset

If you have the candidate dataset zip at the repository root, `scripts/seed_dataset.py` ingests the
four supplied documents (UK, Germany, France, Italy) through the same `POST /documents` service path
the API uses, with explicit country/language metadata:

```bash
# from the repository root, with the backend venv active
python scripts/seed_dataset.py
```

Running it twice is safe — already-ingested documents are detected by content hash and skipped.
The script also runs two verification checks: that no "suggested test questions" trailer section
leaked into indexed content, and that German diacritics survived the pipeline intact.

Local ignored copies of the dataset and technical brief may live under root `noise/`; copy the zip
back to the repository root before using `seed_dataset.py`.

## Running tests

```bash
cd backend
pytest tests/unit tests/integration -v
```

All tests use the mock embedding provider, so no LLM or embedding API key is required. DB-backed
tests require Postgres through `TEST_DATABASE_URL` and create/drop an isolated temporary database
per test. CI provides this automatically.

For a local no-skip integration run on Windows/PowerShell:

```powershell
npm run db:dev
cd backend
$env:TEST_DATABASE_URL = "postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga"
python -m pytest tests/integration -q -rs
```

The test fixture renders SQLAlchemy URLs with `hide_password=False`; otherwise SQLAlchemy masks the
password as `***`, which makes temporary test-database creation fail authentication.

## Linting

```bash
ruff check app tests ../scripts
```

## Authentication

Set `AUTH_MODE` in `.env`:

- `disabled` (default) — no auth; every request uses `DEFAULT_WORKSPACE_ID`. This is what tests and
  a fresh local clone use out of the box.
- `jwt` — real accounts with per-user data isolation. Requires `JWT_SECRET` (the app refuses to
  start without it in this mode — see `_validate_auth_config` in `app/main.py`). Generate one with:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `api_key` — app-level API key protection for demos/integrations. Requires `APP_API_KEY` to be set
  to a non-placeholder value. Protected requests must include `X-API-Key: <APP_API_KEY>` and use
  `DEFAULT_WORKSPACE_ID`. API-key callers are treated as upload admins. Missing and incorrect API
  keys intentionally return the same public `UNAUTHORIZED` response; the server logs keep the
  internal reason.

Flow:

1. `POST /auth/register {"email": ..., "password": ...}` → creates the account with a fresh,
   randomly generated `workspace_id`, returns `{access_token, token_type, expires_in, workspace_id}`.
2. `POST /auth/login {"email": ..., "password": ...}` → same response shape for an existing account.
3. Send the token on every subsequent request: `Authorization: Bearer <access_token>`.

`/documents` and `/ask` both resolve their workspace from the token via `get_workspace_id`
(`app/api/dependencies.py`) — no route-specific auth code was needed because both already depended
on that one function. Every document/chunk/question/answer table already carries a `workspace_id`
column and every query already filters by it, so two different users' documents genuinely cannot
appear in each other's `GET /documents`/`/ask` results — proven in
`tests/integration/test_auth_api.py::test_two_users_documents_do_not_collide`, which registers two
users, uploads a distinct document as each, and asserts the two `GET /documents` results are
disjoint.

Login/register intentionally return the identical `INVALID_CREDENTIALS` error for both "wrong
password" and "no such account" — distinguishing them would let a caller enumerate registered
emails.

There is no refresh-token rotation, logout/revocation, or rate-limiting on `/auth/login`
(brute-force protection) — access tokens are short-lived (60 minutes by default,
`JWT_EXPIRES_MINUTES`) but a compromised token is valid until it expires; acceptable for a prototype,
a real deployment would want refresh tokens plus a revocation list or shorter expiry.

## Provider modes

Set `EMBEDDING_PROVIDER` in `.env`:

- `gemini` (default) — requires `GEMINI_API_KEY`. Real semantic embeddings via
  `langchain-google-genai` (`GoogleGenerativeAIEmbeddings`). Use
  `EMBEDDING_MODEL=models/gemini-embedding-001` and `EMBEDDING_DIMENSION=3072`.
- `openai` — requires `OPENAI_API_KEY`. Real semantic embeddings via `langchain-openai`.
- `mock` — deterministic, offline, no credentials required. This is only for tests and explicit
  offline smoke checks. It does **not** produce real semantic search quality, so do not use it to
  judge retrieval relevance.
- `azure_openai` — interface exists but is not implemented in this MVP (raises
  `NotImplementedError`); documented as a stretch item.

For Docker Compose runs, the backend container reads `backend/.env`, so put
`GEMINI_API_KEY` there. Root `.env` is for Compose-level values such as `JWT_SECRET`,
`ADMIN_EMAILS`, and local Postgres settings.

Retrieval is wrapped in a small in-memory TTL/LRU cache by default
(`RETRIEVAL_CACHE_ENABLED=true`). It has two layers:

- question-type cache: similar question embeddings, within the same workspace and filters, map to
  previously selected chunk IDs;
- hot chunk cache: those chunk IDs map to the selected chunk text and metadata.

The cache stores question embeddings and chunk IDs, not raw questions or final answers. Entries are
short-lived, size-limited, tenant-scoped, and invalidated when the Chroma collection chunk count
changes.

Final chunk selection keeps a per-document diversity cap for cross-document questions, but does not
apply that cap when all eligible candidates come from a single document. This avoids suppressing a
later relevant section in country-specific or document-specific answers.

Prompts are versioned Markdown files in `backend/prompts/`, selected by `PROMPT_VERSION`. The app
loads them at startup and refuses to start if the configured prompt version is not available.

## Known limitations

- **PDF table extraction is table-aware for born-digital grid tables.** The current implementation
  extracts whole-table and row-level chunks with PyMuPDF line-based table detection. This is strong
  for the supplied PDFs, but scanned PDFs, weak table borders, and complex layouts still need OCR or
  a stronger layout model.
- **PDF section-heading detection is a heuristic**, tuned to this dataset's short sentence-case
  titles (e.g. "Executive summary"). It correctly handles the real dataset's two-column PDFs
  (verified against the actual block coordinates) but is not a general-purpose PDF layout parser.
- **In-process background ingestion.** The API no longer waits for parsing/chunking/embedding during
  `POST /documents`; uploads return as `processing` and a local worker marks them `ready` or
  `failed`. This is intentionally lightweight for reviewer setup. A production deployment should
  replace it with a durable external queue, separate worker containers, retry/dead-letter handling,
  and queue-depth metrics.
- **Auth defaults to disabled** (`AUTH_MODE=disabled`) for local dev/tests. Real per-user isolation
  is available via `AUTH_MODE=jwt` (see Authentication above) but is not the default, so a fresh
  clone is open by default until `.env` is configured. `AUTH_MODE=api_key` provides simple
  app-level protection but does not provide per-user tenancy; use JWT mode for multi-user isolation.
- **No brute-force protection on `/auth/login`** and no refresh-token rotation/revocation. Access
  tokens are short-lived (60 min default) but cannot be invalidated before then. Acceptable for a
  prototype; a production deployment needs rate limiting on auth endpoints and a revocation
  mechanism.
- **No dependency lock file.** `pip install -e .` resolves against the version ranges in
  `pyproject.toml`; a production setup should pin exact versions via `pip-compile`/`uv lock` and run
  `pip-audit` in CI.
- **Every chunk's raw citation text is preserved verbatim** (`raw_text` field) separately from the
  text actually sent to the embedding model/LLM (`content` field, which is a rewritten "semantic
  block" for table rows and may include retrieval-only aliases for German text). `/ask` always
  returns `raw_text` as the API `snippet`.

## Architecture notes

- `create_app(settings: Settings | None = None)` factory pattern (`app/main.py`) — production uses
  the default `Settings()`, tests inject an isolated `Settings` pointing at temp directories. No
  global mutable engine/session state.
- Upload ingestion is status-driven: request handling creates the document and an `ingestion_jobs`
  row; the worker uses a fresh DB session to process the stored source content outside the HTTP
  request lifecycle.
- Layered structure (routes → services → repositories/providers) per the senior-project-pack
  modularity checklist: routes are thin, business logic lives in `services/`, persistence in
  `repositories/`, third-party integrations (Chroma, OpenAI, PyMuPDF) are wrapped behind
  `rag/`/`vectorstores/`/`storage/` interfaces rather than imported directly in services.
- API-only concerns stay in `api/`: routes translate FastAPI upload objects into domain upload DTOs,
  and `api/errors.py` maps domain/service errors to the public error envelope.
- `app/domain/` contains service-layer errors and DTOs that are safe for services, scripts, and tests
  to share without importing FastAPI.
- Answer persistence models for `questions`, `answers`, and `answer_sources` live in
  `repositories/models.py`; `repositories/answers.py` performs ORM writes rather than request-time
  table creation.
- Retrieval is split under `rag/retrieval/` by responsibility: Chroma access, lexical scoring,
  ranking/deduplication, source-label assignment, shared models, and utilities. `rag/retriever.py`
  remains a compatibility export for existing imports.
- Frontend chat state is held in `frontend/src/features/chat/useChatSession.ts`, not inside the
  chat route component, so pending ask responses survive navigation to Upload Evidence or Document
  Library.
- See the root `ARCHITECTURE.md` for the end-to-end design, background ingestion decision, and
  production trade-offs.
- See the root `OPERATIONS.md` for health checks, config validation, retry policy, and logging
  conventions.
