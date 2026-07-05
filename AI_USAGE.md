# AI Usage

AI tools were used as an engineering assistant during this technical test.

## Tools Used

- OpenAI Codex-style coding assistant inside the local project workspace.

## What AI Helped With

- Reading and summarizing the technical brief.
- Drafting and editing FastAPI, React, and test changes.
- Checking architecture trade-offs for synchronous HTTP handling versus background ingestion.
- Updating documentation so design decisions are explicit.

## Verification

Generated code was verified by running:

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/unit tests/integration -q
.venv/Scripts/python.exe -m ruff check app tests ../scripts

cd ../frontend
npm.cmd run build
```

The backend test suite uses mock LLM and embedding providers, isolated temporary Postgres
databases, isolated Chroma directories, and temporary upload storage.

## Risks and Controls

- AI-generated code can miss edge cases, so tests were updated around the behavior change.
- The background worker is intentionally local and lightweight; production should use a durable
  external queue, separate worker process, retry policy, and dead-letter handling.
- Provider outputs are not trusted blindly. Answers are grounded in retrieved snippets and citations
  are validated before a response is returned.
