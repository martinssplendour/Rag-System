# Kintiga Market Access Evidence Assistant

Full-stack MVP for uploading market-access evidence and asking cited questions against it.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, async ingestion decision, trade-offs,
and production next steps.

## Reviewer Orientation

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

## App Start

Create a root `.env` file from the example and set a real `JWT_SECRET`:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the generated value into root `.env` as `JWT_SECRET`.

Then create the backend env file and set `GEMINI_API_KEY` there:

```bash
cp backend/.env.example backend/.env
```

Use the Nginx-fronted Docker Compose setup:

```bash
npm run start
```

Then open:

```text
http://localhost:8080
```

This starts:

- `postgres`: Postgres for users, documents, chunks, ingestion jobs, questions, answers, and
  answer sources.
- `frontend`: Nginx serving the built React/Vite app.
- `backend`: FastAPI on the internal Docker network.

Only Nginx is exposed to the browser. Postgres and FastAPI stay on the Docker network. Frontend
requests use `/api/*`, and Nginx proxies those requests to FastAPI.

## API Documentation

With the Docker Compose app running:

- Swagger UI: `http://localhost:8080/api/docs`
- OpenAPI JSON: `http://localhost:8080/api/openapi.json`

When running the backend directly from `backend/`:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

For split local development, run only Postgres in Docker and run the backend/frontend directly.
Use this when you want hot reload without rebuilding the full Docker app:

```bash
npm run db:dev
```

This recreates only the Postgres container with `localhost:5433` exposed and keeps the dev database
in the `postgres-dev-data` Docker volume.

Use this `backend/.env` database URL for that mode. If you changed `POSTGRES_PASSWORD` in root
`.env`, use that same password here:

```text
DATABASE_URL=postgresql+asyncpg://kintiga:kintiga_dev_password@localhost:5433/kintiga
```

Then start the API and frontend in separate terminals:

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd frontend
npm run dev
```

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

## RAG Evaluation

The evaluator uses the 10 suggested questions from the technical-test PDF:

```bash
python scripts/evaluate_rag.py --mode live
python scripts/evaluate_rag.py --mode mock
```

It seeds the provided candidate dataset through `POST /documents`, calls `/ask`, and checks expected
documents, valid source cards, source concepts, and configured answer concepts. The PDF's example
answer is used as an answer-concept check for the UK evidence-gaps question.

Live mode uses Gemini and is the default quality check. Mock mode remains available only as an
explicit offline pipeline smoke check. The dataset zip must be available locally as
`kintiga_market_access_candidate_dataset.zip`; live/default mode also requires `GEMINI_API_KEY`
in `backend/.env`.

Local copies of the PDF brief, build specs, candidate dataset zip, and senior-project-pack can be
kept in ignored `noise/`. To evaluate from there, pass an explicit dataset path:

```bash
python scripts/evaluate_rag.py --mode live --dataset noise/kintiga_market_access_candidate_dataset.zip
```

The chunking and table-extraction quality audit is documented in
[docs/CHUNKING_QUALITY_REPORT.md](docs/CHUNKING_QUALITY_REPORT.md).

## Provider Modes

Gemini mode is the default:

```bash
npm run start
```

Default mode uses:

- `postgres-gemini-data` for app metadata
- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `EMBEDDING_DIMENSION=3072`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`
- `AUTH_MODE=jwt`
- `JWT_SECRET` loaded from your local `.env`
- `GEMINI_API_KEY` loaded from your local `backend/.env`
- `ADMIN_EMAILS=admin@example.com` unless overridden
- `backend-data` for uploaded files and Chroma vectors

Only admin users can upload evidence. To make your own login an admin, set:

```text
ADMIN_EMAILS=your-email@example.com
```

Then register or log in with that same email.

Uploads ask only for country and language. Country is a dropdown; language can be selected or left
as auto-detect. Auto-detection runs locally during background ingestion and stores stable language
codes such as `en` and `de`.

Explicit mock mode:

```bash
npm run app:mock
```

Mock mode is only for CI/offline smoke checks. It uses deterministic fake embeddings and fake answer
generation, so it should not be used to judge retrieval quality. It uses separate mock Postgres and
backend data volumes so mock vectors cannot mix with Gemini vectors.

Separate live-volume mode:

```bash
npm run app:live
```

This uses separate Postgres and backend data volumes:

- `postgres-live-data` for app metadata
- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `EMBEDDING_DIMENSION=3072`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`
- `backend-live-data` for uploaded files and Chroma vectors

The separate Postgres and backend data volumes matter when you want to keep a second Gemini dataset
isolated from the default local app data.

Stop the stack:

```bash
npm run app:down
```

Stop the live stack:

```bash
npm run app:down:live
```

Stop the mock stack:

```bash
npm run app:down:mock
```

View logs:

```bash
npm run app:logs
```

## Notes

- Docker Desktop or Docker Engine is required for the one-command stack.
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
- Frontend-only development can still use `cd frontend && npm run dev`, but the normal app
  entry point is the Nginx/Compose command above.
