# Kintiga Evidence Assistant

Full-stack MVP for uploading market-access evidence and asking cited questions against it.

## Run The System

### 1. Containerized App

This is the normal way to run the full system. It starts Postgres, the FastAPI backend, and the
React frontend behind Nginx.

Create a root `.env` file and set a real `JWT_SECRET`:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the generated value into root `.env` as `JWT_SECRET`.

Create the backend env file and set `GEMINI_API_KEY`:

```bash
cp backend/.env.example backend/.env
```

Start the containerized app:

```bash
npm run start
```

Open:

```text
http://localhost:8080
```

The containerized app starts:

- `postgres`: app metadata, documents, chunks, ingestion jobs, questions, answers, and answer
  sources.
- `backend`: FastAPI on the internal Docker network.
- `frontend`: Nginx serving the built React/Vite app and proxying `/api/*` to FastAPI.

Only Nginx is exposed to the browser. Postgres and FastAPI stay on the Docker network.

API docs for the containerized app:

- Swagger UI: `http://localhost:8080/api/docs`
- OpenAPI JSON: `http://localhost:8080/api/openapi.json`

Stop the stack:

```bash
npm run app:down
```

View logs:

```bash
npm run app:logs
```

### 2. Containerized Mock Mode

Use mock mode only for offline smoke checks. It uses deterministic fake embeddings and fake answer
generation, so it should not be used to judge retrieval quality.

```bash
npm run app:mock
```

Mock mode uses separate mock Postgres and backend data volumes so mock vectors cannot mix with
Gemini vectors.

Stop mock mode:

```bash
npm run app:down:mock
```

### 3. Separate Live-Volume Mode

Use this when you want a second Gemini-backed app state isolated from the default local app data.

```bash
npm run app:live
```

This uses separate Postgres and backend data volumes:

- `postgres-live-data` for app metadata.
- `backend-live-data` for uploaded files and Chroma vectors.

Stop live-volume mode:

```bash
npm run app:down:live
```

### 4. Split Local Development

Use this when you want backend/frontend hot reload without rebuilding the full Docker app. Postgres
runs in Docker, while the backend and frontend run directly on your machine.

Start only the dev Postgres container:

```bash
npm run db:dev
```

This exposes Postgres on `localhost:5433` and stores the dev database in the `postgres-dev-data`
Docker volume.

Use this value in `backend/.env`. If you changed `POSTGRES_PASSWORD` in root `.env`, use that same
password here:

```text
DATABASE_URL=postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga
```

Start the API:

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Direct backend API docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### 5. RAG Evaluation Script

The evaluator seeds the candidate dataset through `POST /documents`, calls `/ask`, and checks
expected documents, valid source cards, source concepts, configured source IDs, and answer concepts
in live mode.

Live mode is the meaningful quality check:

```bash
python scripts/evaluate_rag.py --mode live --dataset noise/kintiga_market_access_candidate_dataset.zip
```

Mock mode is only an offline pipeline smoke check:

```bash
python scripts/evaluate_rag.py --mode mock --dataset noise/kintiga_market_access_candidate_dataset.zip
```

The script loads `.env` and `backend/.env`, uses `EVAL_DATABASE_URL`, `DATABASE_URL`, or the
configured backend database URL, and creates an isolated temporary evaluation database. Chroma uses a
temporary local directory for the run. For the default local database on `localhost:5433`, the
evaluator starts a temporary local PostgreSQL server itself using local PostgreSQL tools (`initdb`,
`postgres`, and `pg_ctl` for cleanup) if nothing is already listening there. You do not need a second
terminal for Postgres.

Pass `--no-start-postgres` when you want to manage Postgres yourself, or `--start-postgres` only
when you explicitly want the bundled Docker Compose Postgres service.

## Runtime Defaults

The default containerized app is a LangChain-backed RAG application using Gemini:

- `postgres-gemini-data` for app metadata.
- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `EMBEDDING_DIMENSION=3072`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`
- `AUTH_MODE=jwt`
- `JWT_SECRET` loaded from root `.env`
- `GEMINI_API_KEY` loaded from `backend/.env`
- `ADMIN_EMAILS=admin@example.com` unless overridden.
- `backend-data` for uploaded files and Chroma vectors.

LangChain is used behind the backend provider abstraction for chat-model orchestration, structured
answer generation, and real embedding integrations. The app keeps provider access swappable so
Gemini, OpenAI, Azure OpenAI, or mock providers can be selected without changing API routes.

Only admin users can upload evidence when auth is enabled. To make your own login an admin, set:

```text
ADMIN_EMAILS=your-email@example.com
```

Then register or log in with that same email.

Uploads ask only for country and language. Country is a dropdown; language can be selected or left
as auto-detect. Auto-detection runs locally during background ingestion and stores stable language
codes such as `en` and `de`.

## Monitoring And Operations

The app includes lightweight monitoring and operational visibility for local and containerized runs.

Health endpoints:

- `GET /health` confirms the API process is alive.
- `GET /health/ready` confirms the API can reach Postgres and Chroma before traffic is routed to it.

Container logs:

```bash
npm run app:logs
```

Backend logs include:

- request IDs via `X-Request-ID`;
- route, status code, and latency for completed requests;
- ingestion job lifecycle events, including retries and final failures;
- document deletion and background cleanup events;
- safe authentication failure reasons for API-key mode.

Logs intentionally avoid full document text, full user questions, JWTs, API keys, and provider
secrets. The Docker Compose backend uses `/health/ready` as its healthcheck, and the frontend waits
for the backend to become healthy before serving the full stack. See [OPERATIONS.md](OPERATIONS.md)
for config validation, retry behavior, evaluator runtime details, and safe logging rules. A full
LLM token/cost ledger and LLM-specific tracing are documented as production follow-ups rather than
core MVP requirements.

Current caching is intentionally narrow. Prompt templates are cached locally after loading, and
retrieval uses a tenant-scoped TTL/LRU cache for similar question embeddings and selected chunk
payloads. Provider-level prompt caching and full answer caching are not implemented in the MVP.
If provider prompt caching is added later, cache keys must include provider, model, prompt version,
workspace, document/filter scope, and collection version, and usage records should show whether a
provider cache was used.

## Reviewer Orientation

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, async ingestion decision, trade-offs,
and production next steps.

- Frontend `App.tsx` is a thin session gate. The product UI is split by feature under
  `frontend/src/features/`, with shared UI/helpers in `frontend/src/components/`,
  `frontend/src/lib/`, and `frontend/src/constants/`.
- Chat state lives above the chat view in `frontend/src/features/chat/useChatSession.ts`, so a
  pending `/ask` request can finish while the user visits Upload Evidence or Document Library. The
  session transcript is stored in browser `sessionStorage` and is cleared on logout or Restart.
- Backend routes translate HTTP/FastAPI concerns into domain inputs and safe error responses.
  Service-layer errors and upload DTOs live in `backend/app/domain/`; use-case orchestration lives
  in `backend/app/services/`; persistence and ORM models live in `backend/app/repositories/`.
- Retrieval internals are split under `backend/app/rag/retrieval/` for Chroma access, lexical
  scoring, ranking, source labels, and shared models. `backend/app/rag/retriever.py` remains as a
  compatibility export for existing imports.
- German evidence remains cited in German. During ingestion, deterministic English retrieval aliases
  are appended only to searchable chunk content for German documents; `raw_text` snippets stay
  verbatim for auditability.
- Answer history uses SQLAlchemy ORM models for `questions`, `answers`, and `answer_sources`.

## Quality Gates

GitHub Actions runs CI on pushes to `main` and on pull requests:

- Backend lint: `ruff check app tests ../scripts`
- Backend tests: `pytest tests/unit tests/integration -q`
- Backend Postgres smoke: app startup and readiness query against Postgres
- Frontend tests: `npm run test`
- Frontend build: `npm run build`

For a full local backend run with the dev Postgres container:

```powershell
npm run db:dev
cd backend
$env:TEST_DATABASE_URL = "postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga"
python -m pytest tests/unit tests/integration -q
```

If a Windows temp/cache directory is locked, point pytest at a workspace temp folder:

```powershell
New-Item -ItemType Directory -Force ..\.tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path ..\.tmp\pytest).Path
$env:TMP = $env:TEMP
python -m pytest tests/unit tests/integration -q --basetemp ..\.tmp\pytest-basetemp -o cache_dir=..\.tmp\pytest-cache
```

The chunking and table-extraction quality audit is documented in
[docs/CHUNKING_QUALITY_REPORT.md](docs/CHUNKING_QUALITY_REPORT.md).

## Notes

- Docker Desktop or Docker Engine is required for the containerized app.
- The default Compose setup uses Gemini embeddings and Gemini answer generation; it requires
  `GEMINI_API_KEY` in `backend/.env`.
- Mock mode is explicit and only intended for offline smoke checks and CI-style plumbing tests.
- Evidence uploads accept PDF, TXT, and DOCX files.
- Upload requests return quickly with `status="processing"`; a background ingestion worker parses,
  chunks, embeds, and marks documents `ready` or `failed`.
- Admin users can delete documents. Deletion soft-hides the document first, then cleans Chroma
  vectors, chunks, stored files, ingestion jobs, and retrieval caches in the background.
- Keep local-only artifacts such as `.env`, `backend/.env`, `backend/data/`, `frontend/node_modules/`,
  and `noise/` uncommitted. They are ignored intentionally.
