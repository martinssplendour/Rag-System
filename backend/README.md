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
  chunk (table-row-aware) → embed → persist (SQLite + Chroma) → mark `ready`/`failed`
- Swagger/OpenAPI at `/docs`, raw schema at `/openapi.json`

## Prerequisites

- Python 3.11+
- No external services required for local development — everything runs against local SQLite +
  Chroma with the mock embedding provider by default.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
cp .env.example .env          # defaults are already local-only; edit only if needed
```

## Running the API

```bash
uvicorn app.main:app --reload --port 8000
```

- Health check: `http://localhost:8000/health`
- Readiness check: `http://localhost:8000/health/ready`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

Local data (SQLite DB, Chroma collection, uploaded files) is written to `./data/` and is
gitignored. Delete that directory to reset to a clean state.

`POST /documents` validates and stores the uploaded content, creates a durable `ingestion_jobs`
row, and returns quickly with the document in `processing` status. The in-process background worker
started by FastAPI then performs parsing, chunking, embedding, and Chroma upsert. `GET /documents`
is the status source of truth.

Uploads are checked for size, extension, and actual file content. In JWT mode, uploads are
admin-only. If background ingestion fails, the worker retries up to `INGESTION_JOB_MAX_ATTEMPTS`
before marking the document `failed`; stack traces stay in server logs and users only receive safe
status/error messages.

## Seeding the real dataset

If you have the candidate dataset zip locally, `scripts/seed_dataset.py` ingests the four supplied
documents (UK, Germany, France, Italy) through the same `POST /documents` service path the API uses,
with explicit country/language metadata:

```bash
# from the repository root, with the backend venv active
python scripts/seed_dataset.py
```

Running it twice is safe — already-ingested documents are detected by content hash and skipped.
The script also runs two verification checks: that no "suggested test questions" trailer section
leaked into indexed content, and that German diacritics survived the pipeline intact.

## Running tests

```bash
cd backend
pytest tests/unit tests/integration -v
```

All tests use the mock embedding provider — no API key or network access is required. Each test
gets a fully isolated app instance (temp SQLite file, temp Chroma directory) via the `create_app()`
factory, so tests don't share state or require a running server.

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

**Not implemented**: `AUTH_MODE=api_key` is declared in `Settings` (`app_api_key` field) but has no
enforcement code behind it — it is inert configuration, not a working mode. Only `disabled` and
`jwt` actually do anything. There is also no refresh-token rotation, logout/revocation, or
rate-limiting on `/auth/login` (brute-force protection) — access tokens are short-lived (60 minutes
by default, `JWT_EXPIRES_MINUTES`) but a compromised token is valid until it expires; acceptable for
a prototype, a real deployment would want refresh tokens plus a revocation list or shorter expiry.

## Provider modes

Set `EMBEDDING_PROVIDER` in `.env`:

- `mock` (default) — deterministic, offline, no credentials required. Sufficient for development,
  tests, and demonstrating the pipeline end-to-end. Does **not** produce real semantic search
  quality — do not use it to judge retrieval relevance.
- `openai` — requires `OPENAI_API_KEY`. Real semantic embeddings via `langchain-openai`.
- `gemini` — requires `GEMINI_API_KEY`. Real semantic embeddings via `langchain-google-genai`
  (`GoogleGenerativeAIEmbeddings`). Use `EMBEDDING_MODEL=models/gemini-embedding-001` and
  `EMBEDDING_DIMENSION=3072` — `models/text-embedding-004` returns 404 on the current API
  version/key, confirmed live. Verified end-to-end against the real dataset, including the
  cross-language case: an English question ("What concerns were raised about the German digital
  therapeutic comparator?") correctly retrieves the German-language document in the top result.
- `azure_openai` — interface exists but is not implemented in this MVP (raises
  `NotImplementedError`); documented as a stretch item.

Retrieval is wrapped in a small in-memory TTL/LRU cache by default
(`RETRIEVAL_CACHE_ENABLED=true`). It has two layers:

- question-type cache: similar question embeddings, within the same workspace and filters, map to
  previously selected chunk IDs;
- hot chunk cache: those chunk IDs map to the selected chunk text and metadata.

The cache stores question embeddings and chunk IDs, not raw questions or final answers. Entries are
short-lived, size-limited, tenant-scoped, and invalidated when the Chroma collection chunk count
changes.

## Known limitations

- **PDF table rows are not individually chunked.** Unlike the pipe-delimited tables in the `.txt`
  files (which are split one row per chunk with the original row preserved verbatim as the citable
  snippet), PDF-extracted table text is kept as a single chunk per table. PyMuPDF's extracted word
  order does not reliably map to unambiguous cell boundaries for an arbitrary grid table without a
  dedicated table-extraction library (e.g. `camelot`/`pdfplumber`), and a wrong guess would silently
  mislabel which cell a snippet came from — worse than the current coarser-grained but always-correct
  fallback. Deferred as a production improvement.
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
  clone is open by default until `.env` is configured. `AUTH_MODE=api_key` is declared but not
  implemented — there is no code path that checks it.
- **No brute-force protection on `/auth/login`** and no refresh-token rotation/revocation. Access
  tokens are short-lived (60 min default) but cannot be invalidated before then. Acceptable for a
  prototype; a production deployment needs rate limiting on auth endpoints and a revocation
  mechanism.
- **No dependency lock file.** `pip install -e .` resolves against the version ranges in
  `pyproject.toml`; a production setup should pin exact versions via `pip-compile`/`uv lock` and run
  `pip-audit` in CI.
- **Every chunk's raw citation text is preserved verbatim** (`raw_text` field) separately from the
  text actually sent to the embedding model/LLM (`content` field, which is a rewritten "semantic
  block" for table rows only). Part 2 must always return `raw_text` as the API `snippet` — see the
  interface contract in `BUILD_SPEC_PART1_INGESTION.md` section 3.

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
- See the root `ARCHITECTURE.md` for the end-to-end design, background ingestion decision, and
  production trade-offs.
- See the root `OPERATIONS.md` for health checks, config validation, retry policy, and logging
  conventions.
