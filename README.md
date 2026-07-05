# Kintiga Market Access Evidence Assistant

Full-stack MVP for uploading market-access evidence and asking cited questions against it.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, async ingestion decision, trade-offs,
and production next steps.

## One-Command App Start

Use the Nginx-fronted Docker Compose setup in mock/offline mode:

```bash
npm run app
```

Then open:

```text
http://localhost:8080
```

This starts:

- `frontend`: Nginx serving the built React/Vite app.
- `backend`: FastAPI on the internal Docker network.

Only Nginx is exposed to the browser. Frontend requests use `/api/*`, and Nginx proxies those
requests to FastAPI.

## Mock vs Live Mode

Mock mode is the default:

```bash
npm run app
```

Mock mode uses:

- `EMBEDDING_PROVIDER=mock`
- `LLM_PROVIDER=mock`
- `AUTH_MODE=disabled` for zero-secret local setup
- `ADMIN_EMAILS=admin@example.com` unless overridden; the UI uses this to show upload controls
- a separate `backend-mock-data` Docker volume

To make your own login appear as an admin in the UI, create a root `.env` file from `.env.example`
and set:

```text
ADMIN_EMAILS=your-email@example.com
```

Then register or log in with that same email.

For enforced JWT auth, set `AUTH_MODE=jwt` and a strong `JWT_SECRET` in the root `.env` or
`backend/.env` before starting the stack.

Live Gemini mode:

```bash
npm run app:live
```

Live mode reads secrets from `backend/.env` and uses:

- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `EMBEDDING_DIMENSION=3072`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`
- a separate `backend-live-data` Docker volume

The separate volumes matter because mock embeddings and Gemini embeddings have different vector
dimensions and cannot safely share the same Chroma collection.

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
- Frontend-only development can still use `cd frontend && npm run dev`, but the normal app
  entry point is the Nginx/Compose command above.
