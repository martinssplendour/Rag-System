# Operations Note

## Health Checks

- `GET /health` confirms the API process is alive.
- `GET /health/ready` confirms the API can reach SQLite and Chroma.

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

`AUTH_MODE=jwt` also refuses to start without `JWT_SECRET`.

## Failure Handling

Uploads return quickly with `status="processing"`. The background worker handles parsing, chunking,
embedding, and vector upsert. Failed ingestion jobs are retried up to
`INGESTION_JOB_MAX_ATTEMPTS`. While retrying, the document remains `processing`; after the final
failure, the document is marked `failed`.

Partial chunks and vectors are deleted after failed attempts so a bad ingestion does not leave stale
search results behind.

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

User-facing errors use a safe envelope with a request ID. Stack traces stay server-side.
