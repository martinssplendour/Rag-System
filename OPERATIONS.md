# Operations Note

## Health Checks

- `GET /health` confirms the API process is alive.
- `GET /health/ready` confirms the API can reach Postgres and Chroma.

Use `/health` for lightweight liveness checks and `/health/ready` before routing traffic to the
service.

## Config Discipline

Configuration is declared in `backend/app/core/config.py` and documented in `backend/.env.example`.
Dangerous values fail at startup instead of failing during a user request:

- upload and text limits must be positive;
- chunk size must be positive;
- chunk overlap must be non-negative and smaller than chunk size;
- ingestion retry attempts must be at least one;
- retrieval thresholds must be between zero and one;
- retrieval cache TTL and cache sizes must be positive.

`AUTH_MODE=jwt` refuses to start without `JWT_SECRET`. `AUTH_MODE=api_key` refuses to start unless
`APP_API_KEY` is set to a non-placeholder value; callers pass it in the `X-API-Key` header. Missing
and incorrect API keys return the same public `UNAUTHORIZED` response, while server logs record the
internal reason.

Prompt text lives in versioned Markdown files under `backend/prompts/`. `PROMPT_VERSION` selects
which prompt files are loaded, and the app refuses to start if that version is not present.

The app uses Postgres for users, documents, chunks, ingestion jobs, questions, answers, and answer
sources.
DB-backed tests create isolated temporary Postgres databases through the same SQLAlchemy repository
layer. For local runs, set `TEST_DATABASE_URL` to the dev Postgres container, for example:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga"
python -m pytest tests/integration -q -rs
```

The test fixture must render SQLAlchemy URLs with `hide_password=False`; `str(URL)` masks passwords
as `***`, which breaks temporary database creation.

## Evaluation Runtime

`scripts/evaluate_rag.py` is self-contained for local evaluation. It loads `.env` and `backend/.env`,
uses `EVAL_DATABASE_URL`, `DATABASE_URL`, or the backend `Settings().database_url`, and stores Chroma
data in a temporary directory for the run.

When the configured database URL points at `localhost:5433` and no server is listening there, the
evaluator starts a temporary local PostgreSQL server itself with the installed PostgreSQL binaries:
`initdb` to create the cluster, `postgres` to run it, and `pg_ctl` to stop it during cleanup. This is
the normal one-command path and does not require Docker:

```powershell
python scripts\evaluate_rag.py --mode live --dataset noise\kintiga_market_access_candidate_dataset.zip
```

Use `--no-start-postgres` when a database is already managed externally, or `--start-postgres` only
when you explicitly want to start the bundled Docker Compose Postgres service. Live mode still
requires `GEMINI_API_KEY` or `GOOGLE_API_KEY` in the environment or `backend/.env`.

If an evaluator run is interrupted while using the temporary local PostgreSQL path, stop the server
with the data directory printed by the evaluator:

```powershell
pg_ctl -D "<printed rag-eval temp path>\postgres" -m fast -w stop
```

Answer-history tables are declared in the repository ORM models, not created by request-time DDL.
Service-layer failures use domain errors and are mapped to the public error envelope only at the API
boundary.

## Failure Handling

Uploads return quickly with `status="processing"`. The background worker handles parsing, chunking,
embedding, and vector upsert. Failed ingestion jobs are retried up to
`INGESTION_JOB_MAX_ATTEMPTS`. While retrying, the document remains `processing`; after the final
failure, the document is marked `failed`.

Partial chunks and vectors are deleted after failed attempts so a bad ingestion does not leave stale
search results behind.

Document deletion is also failure-tolerant. The request marks the document `deleted` first, so users
stop seeing it immediately. Cleanup of Chroma vectors, chunks, ingestion jobs, stored files, and
retrieval caches then runs as a background task. Cleanup failures are logged by cleanup area and do
not expose stack traces to the browser.

Frontend chat state is intentionally lightweight. Completed transcript messages are stored in
browser `sessionStorage` and cleared on logout or Restart. Pending ask requests are owned by a
workspace-level hook, so navigating between Chat, Upload, and Document Library does not cancel the
UI update when the backend response returns.

Local-only artifacts are ignored and should stay uncommitted: `.env`, `backend/.env`,
`backend/data/`, `frontend/node_modules/`, and `noise/`. Generated caches and virtualenvs can be
deleted safely and recreated from the documented setup commands.

## Observability

Logs include request IDs, routes, status codes, latency, ingestion job IDs, document IDs, attempt
counts, and chunk counts. Logs do not include full document text, full user questions, JWTs, API
keys, or provider secrets.

Important events include:

- `request_completed`
- `ingestion_job_started`
- `ingestion_job_retrying`
- `ingestion_job_succeeded`
- `ingestion_job_failed_final`
- `document_soft_deleted`
- `document_cleanup_finished`

User-facing errors use a safe envelope with a request ID. Stack traces stay server-side.
