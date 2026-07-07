# Kintiga Market Access Evidence Assistant

Full-stack MVP for uploading market-access evidence and asking cited questions against it.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, async ingestion decision, trade-offs,
and production next steps.

## App Start

Create a root `.env` file from the example and set a real `JWT_SECRET`:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the generated value into `JWT_SECRET`, then use the Nginx-fronted Docker Compose setup in
mock/offline mode:

```bash
npm run start
```

Then open:

```text
http://localhost:8080
```

This starts:

- `postgres`: Postgres for users, documents, chunks, ingestion jobs, questions, and answers.
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

## Quality Gates

GitHub Actions runs CI on pushes to `main` and on pull requests:

- Backend lint: `ruff check app tests ../scripts`
- Backend tests: `pytest tests/unit tests/integration -q`
- Backend Postgres smoke: app startup and readiness query against Postgres
- Frontend build: `npm ci` and `npm run build`

## RAG Evaluation

The evaluator uses the 10 suggested questions from the technical-test PDF:

```bash
python scripts/evaluate_rag.py --mode mock
python scripts/evaluate_rag.py --mode live
```

It seeds the provided candidate dataset through `POST /documents`, calls `/ask`, and checks expected
documents, valid source cards, source concepts, and configured answer concepts. The PDF's example
answer is used as an answer-concept check for the UK evidence-gaps question.

Mock mode is an offline pipeline sanity check. Live mode uses Gemini and is the stronger answer
quality check. The dataset zip must be available locally as
`kintiga_market_access_candidate_dataset.zip`; live mode also requires `GEMINI_API_KEY`.

The chunking and table-extraction quality audit is documented in
[docs/CHUNKING_QUALITY_REPORT.md](docs/CHUNKING_QUALITY_REPORT.md).

## Mock vs Live Mode

Mock mode is the default:

```bash
npm run start
```

Mock mode uses:

- `postgres-data` for app metadata
- `EMBEDDING_PROVIDER=mock`
- `LLM_PROVIDER=mock`
- `AUTH_MODE=jwt`
- `JWT_SECRET` loaded from your local `.env`
- `ADMIN_EMAILS=admin@example.com` unless overridden
- `backend-mock-data` for uploaded files and Chroma vectors

Only admin users can upload evidence. To make your own login an admin, set:

```text
ADMIN_EMAILS=your-email@example.com
```

Then register or log in with that same email.

Uploads ask only for country and language. Country is a dropdown; language can be selected or left
as auto-detect. Auto-detection runs locally during background ingestion and stores stable language
codes such as `en` and `de`.

Live Gemini mode:

```bash
npm run app:live
```

Live mode reads secrets from `backend/.env` and uses:

- `postgres-live-data` for app metadata
- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `EMBEDDING_DIMENSION=3072`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`
- `backend-live-data` for uploaded files and Chroma vectors

The separate Postgres and backend data volumes matter because mock and live runs should not share
document metadata, ingestion state, or Chroma collections. Mock embeddings and Gemini embeddings
also have different vector dimensions and cannot safely share the same Chroma collection.

Stop the stack:

```bash
npm run app:down
```

Stop the live stack:

```bash
npm run app:down:live
```

View logs:

```bash
npm run app:logs
```

## Notes

- Docker Desktop or Docker Engine is required for the one-command stack.
- The default Compose setup uses mock embeddings and mock LLM output so the app runs without paid
  API keys.
- Live mode requires `GEMINI_API_KEY` in `backend/.env`.
- Evidence uploads accept PDF, TXT, and DOCX files.
- Upload requests return quickly with `status="processing"`; a background ingestion worker parses,
  chunks, embeds, and marks documents `ready` or `failed`.
- Admin users can delete documents. Deletion soft-hides the document first, then cleans Chroma
  vectors, chunks, stored files, ingestion jobs, and retrieval caches in the background.
- Frontend-only development can still use `cd frontend && npm run dev`, but the normal app
  entry point is the Nginx/Compose command above.
