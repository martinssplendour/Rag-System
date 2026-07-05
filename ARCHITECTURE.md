# Architecture Note

## Summary

Market Access Evidence Assistant is a small, production-minded RAG application. The local MVP uses
FastAPI, SQLite, local file storage, Chroma, React, and swappable embedding/LLM providers.

```text
Browser / React UI
  |
  | JSON + multipart uploads
  v
FastAPI API
  |-- auth / workspace boundary
  |-- document validation + raw file storage
  |-- SQLite metadata + ingestion_jobs
  |-- background ingestion worker
  |-- Chroma retriever
  '-- LLM answer generator

Local persistence:
  SQLite: users, documents, chunks, ingestion jobs, questions, answers
  Local files: original uploaded evidence
  Chroma: chunk vectors and retrieval metadata
```

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
- persist chunks in SQLite;
- upsert vectors into Chroma;
- mark the document `ready` or `failed`.

This keeps one tenant's large or slow upload from holding an API request open while still preserving
a simple local setup for reviewers. In production, the SQLite job table and in-process worker would
be replaced by a durable external queue and separate worker containers.

## Retrieval and Grounding

At ask time, `/ask` stays synchronous because the user is waiting for an answer. The service:

- checks that matching documents are `ready`;
- embeds the question through the same embedding provider abstraction used at ingestion time;
- retrieves candidates from Chroma;
- filters by workspace, status, country, and document IDs;
- assigns request-local source labels such as `S1`;
- asks the LLM to answer only from retrieved context;
- validates citations before returning the response.

The API returns original `raw_text` snippets, not rewritten embedding text, so citations preserve the
source language and wording.

## Security and Tenancy

- Every document, chunk, question, and answer carries a `workspace_id`.
- JWT mode isolates users by workspace.
- Uploads validate both extension and file content.
- Uploaded files are stored through a storage abstraction, outside the web root.
- The browser never sees provider credentials.
- Answers include a fixed limitation that they are not medical, legal, regulatory,
  reimbursement, or pricing advice.

## Trade-offs

- SQLite + Chroma keep local setup simple and reliable for the technical test.
- The in-process worker demonstrates the correct async architecture without requiring Redis,
  Celery, or hosted infrastructure.
- Chroma is suitable for the supplied dataset; production should move toward managed Postgres with
  pgvector or another evaluated vector backend.
- PDF table extraction is intentionally conservative to avoid returning misleading row-level
  citations.

## Production Next Steps

1. Replace the in-process worker with a durable queue and separately scaled worker containers.
2. Add retry/dead-letter handling and queue-depth metrics.
3. Move local storage to private object storage.
4. Move SQLite/Chroma to Postgres + pgvector with row-level security.
5. Add malware scanning and OCR for larger document workflows.
6. Add evaluation gates for retrieval quality and answer quality before release.
