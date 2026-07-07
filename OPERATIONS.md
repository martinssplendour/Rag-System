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

The app uses Postgres for users, documents, chunks, ingestion jobs, questions, and answers.
DB-backed tests create isolated temporary Postgres databases through the same SQLAlchemy repository
layer.

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
