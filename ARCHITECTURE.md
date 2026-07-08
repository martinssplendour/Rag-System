# Architecture Note

## Summary

Kintiga Evidence Assistant is a small, production-minded RAG application. The Compose MVP uses
FastAPI, Postgres, local file storage, Chroma, React, LangChain, and swappable embedding/LLM
providers.

```text
Browser / React UI
  |
  | JSON + multipart uploads
  v
FastAPI API
  |-- auth / workspace boundary
  |-- document validation + raw file storage
  |-- Postgres metadata + ingestion_jobs
  |-- background ingestion worker
  |-- Chroma-backed retrieval package
  '-- LLM answer generator

Local persistence:
  Postgres: users, documents, chunks, ingestion jobs, questions, answers, answer_sources
  Local files: original uploaded evidence
  Chroma: chunk vectors and retrieval metadata
```

## Code Organization

The implementation is organized to match a structured engineering checklist for modularity,
testability, and maintainable service boundaries:

- The React entry point, `frontend/src/App.tsx`, owns session state and switches between auth and
  workspace screens. Feature UI lives under `frontend/src/features/` (`auth`, `workspace`,
  `upload`, `documents`, `chat`), with shared primitives in `components`, `lib`, and `constants`.
- Chat request state lives in `frontend/src/features/chat/useChatSession.ts` at the workspace level,
  so a pending answer continues if the user navigates away from the chat view and appears when they
  return.
- API routes keep FastAPI-specific concerns at the boundary. They translate upload objects,
  dependency output, and service errors into public request/response shapes.
- `backend/app/domain/` owns service-level errors and upload DTOs, so services do not import
  FastAPI upload classes or API error envelopes.
- Services coordinate use cases; repositories own SQLAlchemy persistence. `questions`, `answers`,
  and `answer_sources` are ORM models in `backend/app/repositories/models.py`, and answer writes go
  through `backend/app/repositories/answers.py`.
- Retrieval internals live under `backend/app/rag/retrieval/` (`models`, `chroma`, `lexical`,
  `ranking`, `source_labels`, `utils`). `backend/app/rag/retriever.py` remains as compatibility
  exports for older imports.
- LangChain is used behind the backend provider abstraction for chat-model orchestration,
  structured answer generation, and real embedding integrations. The rest of the application talks
  to local provider protocols rather than importing LangChain directly in routes or services.

## Sync vs Background Work

`POST /documents` is an async HTTP endpoint, but it does not make the user wait for indexing.

The request does only the fast, user-facing work:

- authenticate and resolve the workspace;
- validate upload shape, file size, extension, and actual file content;
- hash content and reject duplicates;
- store the original file/text;
- create the document row with `status="processing"`;
- create a durable `ingestion_jobs` row;
- return `202 Accepted`.

The background worker owns the slow work:

- read stored source content;
- parse TXT, PDF, or DOCX;
- clean and normalize content;
- chunk evidence;
- call the embedding provider;
- persist chunks in Postgres;
- upsert vectors into Chroma;
- mark the document `ready` or `failed`.

Upload metadata is intentionally narrow. The UI asks only for country and language: country is a
controlled dropdown that also supplies the stored country code, while language can be selected or
left as auto-detect. Explicit user metadata wins; missing language is detected locally during async
ingestion with Lingua, restricted to English, German, French, and Italian, then stored as an ISO
code (`en`, `de`, `fr`, `it`). Header parsing can fill missing fields, but it does not override
user-supplied country/language.

This keeps one tenant's large or slow upload from holding an API request open while still preserving
a simple local setup for reviewers. In production, the Postgres-backed job table and in-process
worker would be replaced by a durable external queue and separate worker containers.

Ingestion failures are handled as job state, not HTTP failures. The worker retries failed jobs up to
`INGESTION_JOB_MAX_ATTEMPTS`, keeps the document in `processing` while retrying, and only marks the
document `failed` after the final attempt. Partial chunks/vectors are cleaned up after each failed
attempt. User-facing failure text is generic; the server logs keep the exception details.

Document deletion follows the same non-blocking principle. `DELETE /documents/{document_id}` is
admin-only and first marks the document `deleted`, which immediately hides it from normal document
lists and retrieval. Cleanup then runs in the background: Chroma vectors, Postgres chunks, ingestion
jobs, the stored original file, and process-local retrieval caches are removed. If cleanup races with
an ingestion job, the worker checks for the deleted status before committing results and discards any
late output.

## Retrieval and Grounding

At ask time, `/ask` stays synchronous because the user is waiting for an answer. The service:

- checks that matching documents are `ready`;
- embeds the question through the same embedding provider abstraction used at ingestion time;
- retrieves candidates from Chroma;
- filters by workspace, status, country, and document IDs;
- assigns stable source labels such as `UK-NICE-001`, based on a stored per-document citation prefix and chunk number;
- asks the LLM to answer only from retrieved context;
- validates citations before returning the response.

The API returns original `raw_text` snippets, not rewritten embedding text, so citations preserve the
source language and wording.

For German documents, ingestion adds deterministic English retrieval aliases to searchable chunk
`content` only. This improves English-to-German retrieval for terms such as additional evidence,
follow-up, subgroup analysis, patient-relevant endpoints, and real-world evidence while leaving
`raw_text` unchanged for citation cards.

The retrieval package keeps provider access, lexical scoring, ranking/deduplication, and source-label
assignment in separate modules behind the same `RetrievalService` contract. That keeps the API and
answer-generation service insulated from Chroma-specific details.

The ranking step enforces a per-document diversity cap only when multiple documents are eligible.
For single-document/country-specific retrieval, the cap is relaxed so a later highly relevant
section from the same document is not excluded from context.

Prompt text is kept in versioned Markdown files under `backend/prompts/`, not embedded directly in
the Python service logic. The code loads the prompt selected by `PROMPT_VERSION`, and startup fails
if the configured prompt version is missing. This keeps prompt changes reviewable and gives a clear
path toward a production prompt registry later.

## Evaluation

`scripts/evaluate_rag.py` is a rule-based quality evaluator for the supplied candidate dataset. It
uses the 10 suggested questions from the technical-test PDF, seeds the four documents through the
public `POST /documents` API, calls `/ask`, and scores:

- whether expected source documents are returned;
- whether source cards are present and well-formed;
- whether source snippets contain expected evidence concepts;
- whether configured answer concepts are present.

The PDF's example answer is used as an answer-concept check for the UK evidence-gaps question. The
evaluator deliberately avoids an LLM-as-judge in the MVP so results are deterministic and easy to
explain. Mock mode checks the pipeline offline; live mode uses Gemini and is the stronger answer
quality check. For local runs, the evaluator loads `.env` and `backend/.env`, uses the configured
database URL, writes Chroma data to a temporary local directory, and creates a temporary database
that is dropped after the run. If the default local database on `localhost:5433` is not running, the
evaluator starts a temporary local PostgreSQL server with the installed PostgreSQL binaries
(`initdb`, `postgres`, and `pg_ctl` for cleanup). `--no-start-postgres` keeps startup fully external
for custom database setups, and `--start-postgres` explicitly uses the bundled Docker Compose
Postgres service.

Latest local verification after the German retrieval-support and ranking changes: live mode passed
all 10 evaluation cases with a 100% average score, including the English question against the German
AMNOG document.

## Testing Approach

The backend has unit tests for chunking, preprocessing, provider factories, retrieval ranking,
citation validation, confidence calculation, auth/security helpers, ingestion retries, and prompt
loading. Integration tests exercise `/health`, `/documents`, `/ask`, auth flows, workspace
isolation, answer persistence, and document deletion against Postgres-backed repositories.

The frontend test suite covers authentication state, upload/document workflows, citation rendering,
source-evidence dialogs, pending answer navigation, and admin-only document deletion. CI runs backend
lint, backend unit/integration tests, a Postgres startup smoke test, frontend tests, and frontend
build.

## Operations

`/health` reports that the API process is alive. `/health/ready` checks that Postgres and Chroma
are reachable before the service is considered ready for traffic. Operational details for
config validation, retry behavior, and safe logging live in `OPERATIONS.md`.

## Caching

The MVP includes a small process-local TTL/LRU retrieval cache with two layers:

- a question-type cache maps similar question embeddings to the chunk IDs selected by retrieval;
- a hot chunk cache maps those chunk IDs to the selected chunk text and metadata.

The cache is tenant-scoped and filter-scoped: workspace, country, document IDs, candidate count,
and a simple Chroma collection version are part of the cache scope. The app stores question
embeddings and chunk IDs, not raw questions or final answers. Entries are short-lived and
size-limited, so the normal Chroma retrieval path remains the source of truth on cache miss or
stale cache.

Prompt templates are also cached process-locally after loading from the versioned Markdown prompt
files. This avoids repeated disk reads, but it does not cache LLM responses or provider prompt
state.

Full answer caching is intentionally not implemented in the MVP. It is easier to make stale or
unsafe in a multi-tenant RAG app because answers depend on the tenant's current ready documents,
retrieval thresholds, model version, prompt version, and citation validation.

Provider-level prompt caching is also not implemented in the MVP. If added later, cache keys must
include provider, model, prompt version, workspace, document/filter scope, and collection version.
LLM usage records should also capture whether a provider cache was used so cost and latency analysis
remain auditable.

## Frontend Session State

The chat UI persists completed transcript messages in `sessionStorage`, keyed by workspace and
email. That storage is convenience state for the browser session and is cleared on logout or when
the user clicks Restart. Pending requests are not stored in browser storage, but the request
lifecycle is owned by the workspace-level chat hook, so switching to Upload Evidence or Document
Library does not drop the response.

Answer rows are still persisted server-side in Postgres. The MVP does not expose a "load historical
conversations" API or paginated conversation history screen; that is a production follow-up if
long-lived chat history becomes part of the product.

## Security and Tenancy

- Every document, chunk, question, and answer carries a `workspace_id`.
- JWT mode isolates users by workspace.
- API-key mode provides simple app-level protection using `X-API-Key` and the default workspace;
  missing and incorrect keys return the same public error to avoid leaking auth details.
- Uploads validate size, extension, and actual file content.
- JWT-mode uploads and document deletion require an admin user.
- Uploaded files are stored through a storage abstraction, outside the web root.
- The browser never sees provider credentials.
- Error responses use a safe envelope with request IDs; stack traces and raw validation inputs are
  not returned to users.
- Answers include a fixed limitation that they are not medical, legal, regulatory,
  reimbursement, or pricing advice.

## Trade-offs

- Postgres + Chroma keep the app close to a production data model while keeping vector search simple
  for the technical test.
- The in-process worker demonstrates the correct async architecture without requiring Redis,
  Celery, or hosted infrastructure.
- Chroma is suitable for the supplied dataset; production should move vector search into pgvector or
  another evaluated managed vector backend once retrieval quality and scale requirements are clearer.
- PDF table extraction is intentionally conservative to avoid returning misleading row-level
  citations.

## Production Next Steps

1. Replace the in-process worker with a durable queue and separately scaled worker containers.
2. Add retry/dead-letter handling and queue-depth metrics.
3. Move local storage to private object storage.
4. Add Alembic migrations and managed Postgres backups; evaluate pgvector for replacing Chroma.
5. Add malware scanning and OCR for larger document workflows.
6. Add an append-only LLM usage/cost ledger and optional OpenTelemetry/Langfuse tracing for
   provider latency, token usage, retries, and cost analysis without logging sensitive evidence.
7. Evaluate provider-level prompt caching only after usage data shows repeated long prompts; scope
   cache keys by provider, model, prompt version, workspace, document/filter scope, and collection
   version.
8. Promote live RAG evaluation thresholds into CI/CD before release.
