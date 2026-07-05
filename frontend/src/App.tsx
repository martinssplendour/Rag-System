import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clipboard,
  FileText,
  FolderOpen,
  LogOut,
  MessageSquareText,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Upload,
  UploadCloud,
  User,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  askQuestion,
  listDocuments,
  login,
  register,
  uploadDocument,
} from "./api";
import type {
  AnswerSource,
  ApiErrorEnvelope,
  AskResponse,
  AuthSession,
  Confidence,
  DocumentItem,
  DocumentStatus,
} from "./types";

const SESSION_STORAGE_KEY = "kintiga.auth.session";

type View = "chat" | "upload" | "documents";
type AuthMode = "login" | "register";
type UploadMode = "file" | "text";

type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; response: AskResponse };

function readStoredSession(): AuthSession | null {
  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as AuthSession;
    if (!parsed.accessToken || !parsed.workspaceId || !parsed.email) {
      return null;
    }
    return { ...parsed, isAdmin: Boolean(parsed.isAdmin) };
  } catch {
    return null;
  }
}

function storeSession(session: AuthSession | null): void {
  if (!session) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function App() {
  const [session, setSession] = useState<AuthSession | null>(() => readStoredSession());

  const handleAuthenticated = (nextSession: AuthSession) => {
    storeSession(nextSession);
    setSession(nextSession);
  };

  const handleLogout = () => {
    storeSession(null);
    setSession(null);
  };

  if (!session) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }

  return <Workspace session={session} onLogout={handleLogout} />;
}

function AuthScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitLabel = mode === "login" ? "Sign in" : "Create account";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Email is required.");
      return;
    }
    if (mode === "register" && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (mode === "login" && !password) {
      setError("Password is required.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response =
        mode === "login"
          ? await login(email.trim(), password)
          : await register(email.trim(), password);
      onAuthenticated({
        accessToken: response.access_token,
        workspaceId: response.workspace_id,
        email: email.trim().toLowerCase(),
        isAdmin: response.is_admin,
      });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="brand-mark" aria-hidden="true">
          <ShieldCheck size={30} />
        </div>
        <h1 id="auth-title">Kintiga Evidence Assistant</h1>
        <p className="auth-subtitle">Secure market-access evidence workbench</p>

        <div className="segmented-control" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={mode === "login" ? "active" : ""}
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Login
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            className={mode === "register" ? "active" : ""}
            onClick={() => {
              setMode("register");
              setError(null);
            }}
          >
            Register
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            Email
            <input
              autoComplete="email"
              inputMode="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="analyst@example.com"
            />
          </label>
          <label>
            Password
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "login" ? "Your password" : "At least 8 characters"}
            />
          </label>
          {error ? <InlineAlert tone="error" message={error} /> : null}
          <button className="primary-button full-width" type="submit" disabled={isSubmitting}>
            <ShieldCheck size={18} aria-hidden="true" />
            {isSubmitting ? "Working..." : submitLabel}
          </button>
        </form>
      </section>
    </main>
  );
}

function Workspace({ session, onLogout }: { session: AuthSession; onLogout: () => void }) {
  const [view, setView] = useState<View>("chat");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [documentError, setDocumentError] = useState<string | null>(null);

  const refreshDocuments = useCallback(async (options?: { quiet?: boolean }) => {
    if (!options?.quiet) {
      setIsLoadingDocuments(true);
    }
    setDocumentError(null);
    try {
      const response = await listDocuments(session.accessToken);
      setDocuments(response.items);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onLogout();
        return;
      }
      setDocumentError(errorMessage(caught));
    } finally {
      if (!options?.quiet) {
        setIsLoadingDocuments(false);
      }
    }
  }, [onLogout, session.accessToken]);

  useEffect(() => {
    void refreshDocuments();
  }, [refreshDocuments]);

  const readyCount = documents.filter((document) => document.status === "ready").length;
  const hasProcessingDocuments = documents.some((document) => document.status === "processing");
  const failedCount = documents.filter((document) => document.status === "failed").length;

  useEffect(() => {
    if (!hasProcessingDocuments) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refreshDocuments({ quiet: true });
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [hasProcessingDocuments, refreshDocuments]);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sidebar-brand">
          <div className="brand-mark small" aria-hidden="true">
            <ShieldCheck size={22} />
          </div>
          <div>
            <strong>Kintiga</strong>
            <span>Evidence Assistant</span>
          </div>
        </div>

        <nav className="nav-list">
          <NavButton
            icon={<MessageSquareText size={18} />}
            label="Evidence Chat"
            isActive={view === "chat"}
            onClick={() => setView("chat")}
          />
          {session.isAdmin ? (
            <NavButton
              icon={<Upload size={18} />}
              label="Upload Evidence"
              isActive={view === "upload"}
              onClick={() => setView("upload")}
            />
          ) : null}
          <NavButton
            icon={<FolderOpen size={18} />}
            label="Document Library"
            isActive={view === "documents"}
            onClick={() => setView("documents")}
          />
        </nav>

        <div className="sidebar-summary" aria-label="Evidence summary">
          <Metric label="Ready" value={readyCount} tone="success" />
          <Metric label="Total" value={documents.length} tone="neutral" />
          <Metric label="Failed" value={failedCount} tone="danger" />
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Market access evidence workspace</p>
            <h2>{viewTitle(view)}</h2>
          </div>
          <div className="account-strip">
            <div className="account-meta">
              <User size={16} aria-hidden="true" />
              <span>{session.email}</span>
              <span className={`role-badge ${session.isAdmin ? "admin" : "standard"}`}>
                {session.isAdmin ? "Admin" : "User"}
              </span>
            </div>
            <button className="icon-text-button" type="button" onClick={onLogout}>
              <LogOut size={17} aria-hidden="true" />
              Logout
            </button>
          </div>
        </header>

        <main className="workspace-content">
          {view === "chat" ? (
            <EvidenceChat
              documents={documents}
              isLoadingDocuments={isLoadingDocuments}
              token={session.accessToken}
              onAuthExpired={onLogout}
            />
          ) : null}
          {view === "upload" && session.isAdmin ? (
            <UploadEvidence
              token={session.accessToken}
              onUploaded={async () => {
                await refreshDocuments();
                setView("documents");
              }}
              onAuthExpired={onLogout}
            />
          ) : null}
          {view === "upload" && !session.isAdmin ? (
            <section className="panel">
              <EmptyState
                icon={<ShieldCheck size={30} />}
                title="Admin access required"
                detail="Only configured admin users can upload evidence documents."
              />
            </section>
          ) : null}
          {view === "documents" ? (
            <DocumentLibrary
              documents={documents}
              error={documentError}
              isLoading={isLoadingDocuments}
              onRefresh={refreshDocuments}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}

function UploadEvidence({
  token,
  onUploaded,
  onAuthExpired,
}: {
  token: string;
  onUploaded: () => Promise<void>;
  onAuthExpired: () => void;
}) {
  const [mode, setMode] = useState<UploadMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [country, setCountry] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [language, setLanguage] = useState("");
  const [therapyArea, setTherapyArea] = useState("");
  const [technologyType, setTechnologyType] = useState("");
  const [assessmentBody, setAssessmentBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (mode === "file" && !file) {
      setError("Select a PDF, TXT, or DOCX file.");
      return;
    }
    if (mode === "text" && (!title.trim() || !text.trim())) {
      setError("Direct text requires a title and evidence text.");
      return;
    }

    const formData = new FormData();
    if (mode === "file" && file) {
      formData.append("file", file);
    }
    if (mode === "text") {
      formData.append("title", title.trim());
      formData.append("text", text.trim());
    }
    appendIfPresent(formData, "country", country);
    appendIfPresent(formData, "country_code", countryCode);
    appendIfPresent(formData, "language", language);
    appendIfPresent(formData, "therapy_area", therapyArea);
    appendIfPresent(formData, "technology_type", technologyType);
    appendIfPresent(formData, "assessment_body", assessmentBody);

    setIsSubmitting(true);
    try {
      const uploaded = await uploadDocument(token, formData);
      setSuccess(`${uploaded.title} accepted for background processing.`);
      setFile(null);
      setTitle("");
      setText("");
      await onUploaded();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
        return;
      }
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleFileCandidate(candidate: File | undefined) {
    if (!candidate) {
      return;
    }
    const fileName = candidate.name.toLowerCase();
    if (!fileName.endsWith(".pdf") && !fileName.endsWith(".txt") && !fileName.endsWith(".docx")) {
      setError("Only PDF, TXT, and DOCX files are supported.");
      setFile(null);
      return;
    }
    setError(null);
    setFile(candidate);
  }

  return (
    <section className="panel upload-grid" aria-labelledby="upload-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Ingestion</p>
          <h3 id="upload-title">Upload evidence</h3>
        </div>
        <StatusBadge status="processing" label="Async indexing" />
      </div>

      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="segmented-control compact" role="tablist" aria-label="Upload mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "file"}
            className={mode === "file" ? "active" : ""}
            onClick={() => setMode("file")}
          >
            File
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "text"}
            className={mode === "text" ? "active" : ""}
            onClick={() => setMode("text")}
          >
            Direct text
          </button>
        </div>

        {mode === "file" ? (
          <label
            className={`drop-zone ${isDragging ? "dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              handleFileCandidate(event.dataTransfer.files[0]);
            }}
          >
            <UploadCloud size={28} aria-hidden="true" />
            <span>{file ? file.name : "Drop a PDF, TXT, or DOCX file"}</span>
            <small>{file ? formatBytes(file.size) : "or choose a file from disk"}</small>
            <input
              type="file"
              accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => handleFileCandidate(event.target.files?.[0])}
            />
          </label>
        ) : (
          <div className="field-stack">
            <label>
              Title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="NICE oncology assessment summary"
              />
            </label>
            <label>
              Evidence text
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Paste the evidence text to index"
                rows={9}
              />
            </label>
          </div>
        )}

        <div className="metadata-grid">
          <label>
            Country
            <input value={country} onChange={(event) => setCountry(event.target.value)} />
          </label>
          <label>
            Code
            <input
              value={countryCode}
              onChange={(event) => setCountryCode(event.target.value)}
              placeholder="UK"
            />
          </label>
          <label>
            Language
            <input
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="en"
            />
          </label>
          <label>
            Therapy area
            <input value={therapyArea} onChange={(event) => setTherapyArea(event.target.value)} />
          </label>
          <label>
            Technology type
            <input
              value={technologyType}
              onChange={(event) => setTechnologyType(event.target.value)}
            />
          </label>
          <label>
            Assessment body
            <input
              value={assessmentBody}
              onChange={(event) => setAssessmentBody(event.target.value)}
            />
          </label>
        </div>

        {error ? <InlineAlert tone="error" message={error} /> : null}
        {success ? <InlineAlert tone="success" message={success} /> : null}

        <div className="form-actions">
          <button className="primary-button" type="submit" disabled={isSubmitting}>
            <Upload size={18} aria-hidden="true" />
            {isSubmitting ? "Uploading..." : "Upload evidence"}
          </button>
        </div>
      </form>
    </section>
  );
}

function DocumentLibrary({
  documents,
  isLoading,
  error,
  onRefresh,
}: {
  documents: DocumentItem[];
  isLoading: boolean;
  error: string | null;
  onRefresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("all");
  const [status, setStatus] = useState<DocumentStatus | "all">("all");

  const countries = useMemo(() => {
    return [...new Set(documents.map((document) => document.country).filter(Boolean))]
      .map(String)
      .sort((a, b) => a.localeCompare(b));
  }, [documents]);

  const filteredDocuments = useMemo(() => {
    const normalisedQuery = query.trim().toLowerCase();
    return documents.filter((document) => {
      const searchable = `${document.title} ${document.filename ?? ""}`.toLowerCase();
      return (
        (!normalisedQuery || searchable.includes(normalisedQuery)) &&
        (country === "all" || document.country === country) &&
        (status === "all" || document.status === status)
      );
    });
  }, [country, documents, query, status]);

  return (
    <section className="panel" aria-labelledby="documents-title">
      <div className="panel-heading library-heading">
        <div>
          <p className="eyebrow">Evidence library</p>
          <h3 id="documents-title">Documents</h3>
        </div>
        <button className="icon-text-button" type="button" onClick={() => void onRefresh()}>
          <RefreshCw size={17} aria-hidden="true" />
          Refresh
        </button>
      </div>

      <div className="toolbar">
        <label className="search-field">
          <Search size={17} aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search title or filename"
          />
        </label>
        <label>
          Country
          <select value={country} onChange={(event) => setCountry(event.target.value)}>
            <option value="all">All countries</option>
            {countries.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as DocumentStatus | "all")}
          >
            <option value="all">All statuses</option>
            <option value="ready">Ready</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
          </select>
        </label>
      </div>

      {error ? <InlineAlert tone="error" message={error} /> : null}
      {isLoading ? <LoadingRows /> : null}
      {!isLoading && filteredDocuments.length === 0 ? (
        <EmptyState
          icon={<FileText size={28} />}
          title="No documents found"
          detail="Upload evidence or adjust the current filters."
        />
      ) : null}
      {!isLoading && filteredDocuments.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Country</th>
                <th>Language</th>
                <th>Status</th>
                <th>Chunks</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocuments.map((document) => (
                <tr key={document.document_id}>
                  <td>
                    <div className="document-cell">
                      <FileText size={18} aria-hidden="true" />
                      <div>
                        <strong>{document.title}</strong>
                        <span>{document.filename ?? document.external_document_id}</span>
                      </div>
                    </div>
                  </td>
                  <td>{document.country ?? "Unknown"}</td>
                  <td>{document.language}</td>
                  <td>
                    <StatusBadge status={document.status} />
                  </td>
                  <td>{document.chunk_count}</td>
                  <td>{formatDate(document.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function EvidenceChat({
  token,
  documents,
  isLoadingDocuments,
  onAuthExpired,
}: {
  token: string;
  documents: DocumentItem[];
  isLoadingDocuments: boolean;
  onAuthExpired: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [country, setCountry] = useState("");
  const [documentId, setDocumentId] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const readyDocuments = documents.filter((document) => document.status === "ready");
  const canSubmit = question.trim().length >= 3 && !isSubmitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }

    const trimmedQuestion = question.trim();
    setError(null);
    setMessages((current) => [...current, { id: makeId(), role: "user", content: trimmedQuestion }]);
    setQuestion("");
    setIsSubmitting(true);

    try {
      const response = await askQuestion(token, {
        question: trimmedQuestion,
        country: country.trim() || undefined,
        document_ids: documentId === "all" ? undefined : [documentId],
      });
      setMessages((current) => [...current, { id: makeId(), role: "assistant", response }]);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
        return;
      }
      setError(errorMessage(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="chat-layout" aria-labelledby="chat-title">
      <div className="chat-main panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Grounded Q&A</p>
            <h3 id="chat-title">Evidence chat</h3>
          </div>
          <ConfidenceLegend />
        </div>

        <div className="message-stream" aria-live="polite">
          {messages.length === 0 ? (
            <EmptyState
              icon={<Bot size={30} />}
              title="Ask from uploaded evidence"
              detail="Answers will include confidence, limitations, and source snippets."
            />
          ) : null}
          {messages.map((message) =>
            message.role === "user" ? (
              <article key={message.id} className="message-row user-message">
                <div className="message-avatar">
                  <User size={17} aria-hidden="true" />
                </div>
                <p>{message.content}</p>
              </article>
            ) : (
              <AssistantMessage key={message.id} response={message.response} />
            ),
          )}
          {isSubmitting ? (
            <article className="message-row assistant-message pending">
              <div className="message-avatar">
                <Bot size={17} aria-hidden="true" />
              </div>
              <p>Retrieving evidence and drafting answer...</p>
            </article>
          ) : null}
        </div>

        {error ? <InlineAlert tone="error" message={error} /> : null}

        <form className="ask-form" onSubmit={handleSubmit}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a market-access question"
            rows={3}
          />
          <div className="ask-actions">
            <button className="primary-button" type="submit" disabled={!canSubmit}>
              <Send size={18} aria-hidden="true" />
              {isSubmitting ? "Asking..." : "Ask"}
            </button>
          </div>
        </form>
      </div>

      <aside className="chat-filters panel" aria-label="Ask filters">
        <div className="panel-heading compact-heading">
          <div>
            <p className="eyebrow">Filters</p>
            <h3>Scope</h3>
          </div>
        </div>
        <label>
          Country
          <input
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            placeholder="United Kingdom"
          />
        </label>
        <label>
          Document
          <select
            value={documentId}
            disabled={isLoadingDocuments}
            onChange={(event) => setDocumentId(event.target.value)}
          >
            <option value="all">All ready documents</option>
            {readyDocuments.map((document) => (
              <option key={document.document_id} value={document.document_id}>
                {document.title}
              </option>
            ))}
          </select>
        </label>
        <div className="filter-note">
          <strong>{readyDocuments.length}</strong>
          <span>ready documents available</span>
        </div>
      </aside>
    </section>
  );
}

function AssistantMessage({ response }: { response: AskResponse }) {
  const [copied, setCopied] = useState(false);

  async function copyAnswer() {
    await navigator.clipboard.writeText(response.answer);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <article className="message-row assistant-message">
      <div className="message-avatar">
        <Bot size={17} aria-hidden="true" />
      </div>
      <div className="assistant-content">
        <div className="assistant-header">
          <ConfidenceBadge confidence={response.confidence} />
          <button className="icon-button" type="button" onClick={() => void copyAnswer()} aria-label="Copy answer">
            <Clipboard size={16} aria-hidden="true" />
          </button>
        </div>
        <p className="answer-text">{renderAnswer(response.answer, response.sources)}</p>
        {response.uncertainty ? (
          <div className="uncertainty">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{response.uncertainty}</span>
          </div>
        ) : null}
        <p className="limitations">{response.limitations}</p>
        {response.sources.length > 0 ? <SourceList sources={response.sources} /> : null}
        {copied ? <span className="copy-confirmation">Copied</span> : null}
      </div>
    </article>
  );
}

function SourceList({ sources }: { sources: AnswerSource[] }) {
  return (
    <div className="source-list" aria-label="Answer sources">
      {sources.map((source) => (
        <div className="source-row" key={`${source.document_id}-${source.source_id}`}>
          <div className="source-label">{source.source_id}</div>
          <div>
            <div className="source-title">
              <strong>{source.document_title}</strong>
              <span>{formatScore(source.relevance_score)}</span>
            </div>
            <p>{source.snippet}</p>
            <div className="source-meta">
              <span>{source.country ?? "Unknown country"}</span>
              <span>{source.language ?? "Unknown language"}</span>
              {source.page_number && source.page_number > 0 ? <span>Page {source.page_number}</span> : null}
              {source.section_title ? <span>{source.section_title}</span> : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function NavButton({
  icon,
  label,
  isActive,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`nav-button ${isActive ? "active" : ""}`} type="button" onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "neutral" | "danger";
}) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InlineAlert({ tone, message }: { tone: "error" | "success"; message: string }) {
  const Icon = tone === "error" ? XCircle : CheckCircle2;
  return (
    <div className={`inline-alert ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

function EmptyState({
  icon,
  title,
  detail,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="empty-state">
      <div aria-hidden="true">{icon}</div>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="loading-rows" aria-label="Loading documents">
      <span />
      <span />
      <span />
    </div>
  );
}

function StatusBadge({ status, label }: { status: DocumentStatus; label?: string }) {
  return <span className={`status-badge ${status}`}>{label ?? status}</span>;
}

function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`confidence-badge ${confidence}`}>{confidence} confidence</span>;
}

function ConfidenceLegend() {
  return (
    <div className="confidence-legend" aria-label="Confidence scale">
      <span className="dot high" />
      <span className="dot medium" />
      <span className="dot low" />
    </div>
  );
}

function renderAnswer(answer: string, sources: AnswerSource[]) {
  const knownSources = new Set(sources.map((source) => source.source_id));
  return answer.split(/(\[S\d+\])/g).map((part, index) => {
    const sourceId = part.match(/\[(S\d+)\]/)?.[1];
    if (!sourceId || !knownSources.has(sourceId)) {
      return <span key={`${part}-${index}`}>{part}</span>;
    }
    return (
      <span className="source-token" key={`${sourceId}-${index}`}>
        {part}
      </span>
    );
  });
}

function appendIfPresent(formData: FormData, key: string, value: string): void {
  const trimmed = value.trim();
  if (trimmed) {
    formData.append(key, trimmed);
  }
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    return `${friendlyErrorCode(caught.code)}${caught.message ? `: ${caught.message}` : ""}`;
  }
  if (caught instanceof Error) {
    return caught.message;
  }
  const envelope = caught as ApiErrorEnvelope;
  return envelope.error?.message || "Something went wrong.";
}

function friendlyErrorCode(code?: string): string {
  if (!code) {
    return "Request failed";
  }
  return code
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function viewTitle(view: View): string {
  if (view === "chat") {
    return "Evidence Chat";
  }
  if (view === "upload") {
    return "Upload Evidence";
  }
  return "Document Library";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(value));
}

function formatScore(value: number): string {
  return `${Math.round(value * 100)}% relevance`;
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function makeId(): string {
  return crypto.randomUUID();
}
