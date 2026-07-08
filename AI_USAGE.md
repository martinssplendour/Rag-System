# AI Usage

This project used AI in two ways: during development, to accelerate implementation and review, and
inside the application, to support retrieval-augmented question answering over uploaded evidence.

## Development Use Of AI

I used AI as an engineering accelerator rather than as the architectural decision-maker. Claude was
used as a coding agent to write application code under my direction. The agent was not given an
open-ended instruction to build the system. I first created the system design and used that design
to guide the implementation path, component boundaries, and expected engineering standard.

The implementation was guided by a structured engineering checklist covering modular design,
testability, maintainability, security, clear service boundaries, error handling, observability, and
production-readiness trade-offs. I manually observed the generated code as it was produced and
reviewed the result against that checklist.

Codex was also used as a review and refinement agent. I used it to inspect the code against my list
of engineering practices, identify weak areas, improve documentation, and check that the
implementation remained aligned with the intended architecture.

Google Stitch was used to generate early UI mockups. Those mockups informed the frontend layout and
interaction direction, but the final UI was implemented and reviewed in the application codebase.

The generated code remains my responsibility. I should be able to explain the architecture, justify
the trade-offs, identify failure modes, and describe how the system would be monitored, secured, and
evolved in production.

## Verification Of AI Output

AI-generated implementation work was checked through:

- manual review against the system design;
- inspection of the Git diff for changed files;
- review with Codex using the engineering checklist;
- backend unit tests and integration coverage for API/database behavior;
- frontend tests and build checks;
- RAG evaluation with `scripts/evaluate_rag.py`;
- manual inspection of documentation, run commands, and reviewer setup flow.

The system design acted as the control document. Code changes were expected to follow that design
rather than inventing new architecture during generation.

## Evidence Of Verification

| Requirement | Evidence |
| --- | --- |
| Workspace isolation | `backend/tests/integration/test_auth_api.py` covers separate users/workspaces and confirms documents are not visible across workspaces. |
| Citation integrity | `backend/tests/unit/test_citation_and_confidence.py` rejects unknown source IDs, and `backend/tests/unit/test_evidence_assistant_service.py` covers the citation-repair path. |
| Upload security | `backend/tests/integration/test_documents_api.py` covers file type, empty file, oversized upload, fake PDF, binary TXT, duplicate upload, and direct-text cases; `backend/tests/unit/test_files.py` covers safe filename/path handling. |
| Provider abstraction | `backend/tests/unit/test_llm_providers.py` covers mock and Gemini answer-generator factory paths; `backend/tests/unit/test_embeddings.py` covers mock, Gemini, OpenAI, and rejected/unsupported embedding provider paths. |
| RAG quality | `scripts/evaluate_rag.py` evaluates the supplied dataset against expected documents, source-card shape, source concepts, source IDs where configured, and answer concepts in live mode. |
| Ingestion failure handling | `backend/tests/unit/test_ingestion_worker.py` covers retry and final-failure behavior. |
| Prompt/version controls | `backend/tests/unit/test_prompts.py` verifies versioned prompt loading and refusal for unknown prompt versions. |
| UI behavior | `frontend/src/App.test.tsx` covers login, admin upload controls, citations/source dialog, pending-answer navigation, document deletion, and non-admin restrictions. |

The final local verification pass included `ruff`, backend unit tests, frontend tests, and frontend
build. Database-backed integration tests are present and are run when Postgres is available, including
in CI.

## Design Decisions

The main architecture decisions were defined before AI implementation work began:

- LangChain is used behind local backend interfaces so chat-model and embedding integrations can be
  changed without coupling routes or services directly to a specific provider SDK.
- Postgres stores users, workspaces, documents, chunks, ingestion jobs, questions, answers, and
  answer-source records because these entities need relational constraints, auditability, and
  workspace filtering.
- Chroma stores vector embeddings and retrieval metadata because semantic search is a separate
  retrieval concern from transactional application data.
- Local file storage stores the original uploaded evidence files so source documents remain
  available for ingestion, audit, and reprocessing.
- The answer pipeline returns source cards, confidence, limitations, and insufficient-evidence
  responses so the model output remains explainable and bounded by the uploaded evidence.

AI tools helped implement and refine these decisions, but they did not replace the design process.

## Risks And Mitigations

The main risk of using AI to write code is that it can produce poor engineering practices: unclear
boundaries, hidden coupling, untested behavior, weak error handling, insecure defaults, or code that
appears correct but does not match the intended system design.

I mitigated this by creating the system design first, defining the engineering path the agent had to
follow, observing the generated code, reviewing it with Codex, and testing whether the resulting
system behaved according to the design. The evaluation script also checks whether the RAG behavior
matches the expected source documents and answer concepts.

## Threat And Failure Review

The AI-related threat review focused on:

- prompt injection or unsupported questions causing the model to answer outside the uploaded
  evidence;
- hallucinated citations or source IDs that were not present in the retrieved context;
- cross-workspace data leakage during retrieval or document access;
- sensitive values such as API keys, JWTs, database URLs, full questions, or full document text being
  exposed in logs or sent unnecessarily to model providers;
- ingestion failures leaving documents in an unclear state;
- provider failures causing incomplete or misleading answers.

The implementation addresses these risks through workspace-scoped queries, citation validation,
safe insufficient-evidence responses, constrained provider payloads, upload validation, structured
logging, and ingestion retry/failure states. These controls are covered by the tests and evaluation
evidence listed above.

## Runtime AI Use

This application uses AI for retrieval-augmented question answering over uploaded market-access
evidence documents. AI is not used to make autonomous decisions; responses are constrained to the
uploaded evidence and returned with citations. LangChain is used behind local backend provider
interfaces for chat-model orchestration, structured answer generation, and real embedding
integrations.

## Where AI Is Used

- Embeddings are generated for document chunks during ingestion.
- The same embedding provider embeds user questions at ask time.
- Vector search retrieves relevant chunks from Chroma, with Postgres metadata used for filtering,
  document state, source cards, and answer history.
- A chat model generates a grounded answer from the retrieved evidence context.
- Citation validation checks that returned source IDs exist in the retrieved context before the
  answer is accepted.

## Providers

The default semantic mode uses Gemini:

- `EMBEDDING_PROVIDER=gemini`
- `EMBEDDING_MODEL=models/gemini-embedding-001`
- `LLM_PROVIDER=gemini`
- `CHAT_MODEL=gemini-3.5-flash`

Capability status is intentionally separated:

- Implemented and exercised for this submission: Gemini and the deterministic `mock` provider.
- Implemented as provider-abstraction extension points: OpenAI-compatible integrations.
- Designed extension point: Azure OpenAI. Azure chat configuration exists, but Azure embeddings are
  not implemented in the MVP and should not be described as an exercised runtime path.

The deterministic `mock` provider is available for tests and offline smoke checks, but mock vectors
are not semantically meaningful and should not be used to judge retrieval quality.

## Data Sent To Providers

For embeddings, the provider receives extracted document chunk text during ingestion and the user
question during retrieval.

For answer generation, the provider receives:

- the user question or decomposed sub-question prompt;
- the selected evidence snippets with source labels;
- the versioned system prompt loaded from `backend/prompts/`.

The model is not given unrelated documents, stored files, API keys, JWTs, or full database records.

## Controls

- Prompt text is versioned under `backend/prompts/` and selected by `PROMPT_VERSION`.
- Answers must cite source IDs from the retrieved context.
- If citation validation fails, the service asks the model to repair citations once.
- If citations still fail, or no relevant chunks are retrieved, the API returns an insufficient
  evidence response.
- Confidence is calculated from evidence sufficiency, citation validity, retrieval scores, and
  source coverage.
- Source cards expose auditable snippets, titles, country/language metadata, and relevance scores.
- Retrieval-only English aliases for German text are added to searchable content, not to
  user-facing `raw_text`, so citations remain auditable against the original document.

## Security Measures

- Authentication supports `jwt`, `api_key`, and local `disabled` modes. JWT mode uses signed bearer
  tokens with expiry, and API-key mode compares keys with constant-time comparison.
- Uploads are admin-only when authentication is enabled. Non-admin users can ask questions only over
  documents in their own workspace.
- Workspace IDs are carried through document, chunk, retrieval, and answer queries so one workspace
  cannot retrieve another workspace's evidence.
- Provider credentials such as `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `OPENAI_API_KEY` are loaded
  from environment files and are not sent to the frontend or included in logs.
- The chat model receives only the selected evidence snippets, source labels, and question prompt;
  it does not receive JWTs, API keys, stored files, or unrelated database records.
- File uploads are constrained by configured size limits, accepted file types, parsing limits, and
  ingestion retry limits before content enters the retrieval index.
- Logs record operational metadata such as request IDs, status codes, latency, document IDs, job IDs,
  and chunk counts. They avoid full document text, full questions, tokens, API keys, and provider
  secrets.
- If retrieval or citation validation is insufficient, the API returns a safe insufficient-evidence
  answer instead of allowing an unsupported model response.
- Responses include the standard limitation that answers are based only on uploaded documents and
  are not medical, legal, regulatory, reimbursement, or pricing advice.

## Operational Considerations

The application includes structured operational logging for request flow, ingestion lifecycle,
cleanup activity, authentication failures, and answer generation outcomes. Logs are designed for
debugging and monitoring without recording secrets or full evidence text.

Token/cost tracking and detailed LLM trace observability are production follow-ups. The intended
approach is to keep financial accounting separate from debugging traces: record provider, model,
request ID, workspace ID, token counts, estimated cost, success/failure state, and latency in a
small usage ledger, while keeping optional debugging traces redacted and retention-limited.

Provider-level prompt caching is also a production optimisation rather than an MVP feature. The app
already caches prompt templates locally and uses tenant-scoped retrieval caching, but it does not
cache LLM responses. If provider prompt caching is added, cache keys should include provider, model,
prompt version, workspace, document/filter scope, and collection version, and usage records should
show whether a provider cache was used.

## Evaluation

`scripts/evaluate_rag.py` runs a rule-based RAG quality check against the supplied candidate
dataset. It seeds documents through `POST /documents`, calls `/ask`, and checks expected documents,
source-card shape, evidence concepts, source IDs where configured, and answer concepts in live mode.

Live evaluation uses Gemini and is the meaningful quality gate. Mock mode is only an offline
pipeline smoke check.
