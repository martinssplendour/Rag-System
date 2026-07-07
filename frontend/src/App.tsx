import {
  AlertCircle,
  BookOpen,
  Bot,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  CheckCircle2,
  Clipboard,
  CircleHelp,
  Eye,
  EyeOff,
  FileText,
  FolderOpen,
  Globe2,
  Landmark,
  LockKeyhole,
  LogOut,
  MessageSquareText,
  Paperclip,
  Plus,
  RefreshCw,
  Scale,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Type,
  Upload,
  UploadCloud,
  User,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  askQuestion,
  deleteDocument,
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

const COUNTRY_OPTIONS = ["United Kingdom", "France", "Germany", "Italy"];

const LANGUAGE_OPTIONS = [
  { label: "Auto detect", value: "auto" },
  { label: "English", value: "en" },
  { label: "German", value: "de" },
  { label: "French", value: "fr" },
  { label: "Italian", value: "it" },
];

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
  const [showPassword, setShowPassword] = useState(false);
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
        <div className="auth-brand-mark" aria-hidden="true">
          <div className="brand-mark">
            K
          </div>
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
            <span className="input-with-icon">
              <User size={18} aria-hidden="true" />
              <input
                autoComplete="email"
                inputMode="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="analyst@example.com"
              />
            </span>
          </label>
          <label>
            Password
            <span className="input-with-icon password-field">
              <LockKeyhole size={18} aria-hidden="true" />
              <input
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={mode === "login" ? "Your password" : "At least 8 characters"}
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((current) => !current)}
              >
                {showPassword ? (
                  <EyeOff size={18} aria-hidden="true" />
                ) : (
                  <Eye size={18} aria-hidden="true" />
                )}
              </button>
            </span>
          </label>
          {mode === "login" ? (
            <button
              className="link-button forgot-password"
              type="button"
              onClick={() => setError("Password reset is not available in this demo.")}
            >
              Forgot password?
            </button>
          ) : null}
          {error ? <InlineAlert tone="error" message={error} /> : null}
          <button className="primary-button full-width" type="submit" disabled={isSubmitting}>
            <ShieldCheck size={18} aria-hidden="true" />
            {isSubmitting ? "Working..." : submitLabel}
          </button>
          <div className="auth-divider">
            <span>or</span>
          </div>
          <button className="icon-text-button full-width sso-button" type="button" disabled>
            <Landmark size={18} aria-hidden="true" />
            Continue with SSO
          </button>
          <p className="auth-security-note">
            <ShieldCheck size={18} aria-hidden="true" />
            Your data is encrypted and securely protected
          </p>
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
            K
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

        <div className="sidebar-footer" aria-hidden="true">
          <ChevronsLeft size={19} />
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <p className="topbar-title">Market Access Evidence Workspace</p>
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
          <PageIntro view={view} />
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
              isAdmin={session.isAdmin}
              token={session.accessToken}
              onRefresh={refreshDocuments}
              onAuthExpired={onLogout}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}

function PageIntro({ view }: { view: View }) {
  return (
    <div className="page-intro">
      <p className="eyebrow">Market access evidence workspace</p>
      <h1>{viewTitle(view)}</h1>
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
  const [language, setLanguage] = useState("auto");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleClear() {
    setFile(null);
    setTitle("");
    setText("");
    setCountry("");
    setLanguage("auto");
    setError(null);
    setSuccess(null);
  }

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
    const selectedCountry = COUNTRY_OPTIONS.find((option) => option === country);
    if (!selectedCountry) {
      setError("Select the document country.");
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
    formData.append("country", selectedCountry);
    if (language !== "auto") {
      formData.append("language", language);
    }

    setIsSubmitting(true);
    try {
      const uploaded = await uploadDocument(token, formData);
      setSuccess(`${uploaded.title} uploaded successfully. It will appear in the library when ready.`);
      setFile(null);
      setTitle("");
      setText("");
      setCountry("");
      setLanguage("auto");
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
    <section className="panel upload-panel" aria-labelledby="upload-title">
      <div className="panel-heading upload-heading">
        <div>
          <p className="eyebrow">Ingestion</p>
          <h3 id="upload-title">Upload evidence</h3>
        </div>
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
            <FileText size={17} aria-hidden="true" />
            File
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "text"}
            className={mode === "text" ? "active" : ""}
            onClick={() => setMode("text")}
          >
            <Type size={17} aria-hidden="true" />
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
            <span className="drop-zone-icon" aria-hidden="true">
              <UploadCloud size={30} />
            </span>
            <span>{file ? file.name : "Drop a PDF, TXT, or DOCX file"}</span>
            <small>{file ? formatBytes(file.size) : "or browse from your device"}</small>
            {!file ? <em>Supported: PDF, TXT, DOCX · Max 10 MB</em> : null}
            <span className="choose-file-button">
              <FolderOpen size={18} aria-hidden="true" />
              Choose file
            </span>
            <input
              type="file"
              accept=".pdf,.txt,.docx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => handleFileCandidate(event.target.files?.[0])}
            />
          </label>
        ) : (
          <div className="field-stack direct-text-panel">
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

        <div className="upload-assurance" aria-label="Upload safeguards">
          <span>
            <ShieldCheck size={18} aria-hidden="true" />
            Files are securely processed for evidence retrieval.
          </span>
          <span>
            <Globe2 size={18} aria-hidden="true" />
            Automatic language detection
          </span>
          <span>
            <Sparkles size={18} aria-hidden="true" />
            Source-ready evidence
          </span>
        </div>

        <div className="metadata-grid">
          <label>
            Country
            <select value={country} onChange={(event) => setCountry(event.target.value)}>
              <option value="">Select country</option>
              {COUNTRY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            Language
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error ? <InlineAlert tone="error" message={error} /> : null}
        {success ? <InlineAlert tone="success" message={success} /> : null}

        <div className="form-actions">
          <button className="icon-text-button" type="button" onClick={handleClear}>
            Clear
          </button>
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
  isAdmin,
  token,
  onRefresh,
  onAuthExpired,
}: {
  documents: DocumentItem[];
  isLoading: boolean;
  error: string | null;
  isAdmin: boolean;
  token: string;
  onRefresh: () => Promise<void>;
  onAuthExpired: () => void;
}) {
  const [query, setQuery] = useState("");
  const [country, setCountry] = useState("all");
  const [status, setStatus] = useState<DocumentStatus | "all">("all");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);

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

  const visibleCount = filteredDocuments.length;
  const totalCount = documents.length;

  async function handleDelete(document: DocumentItem) {
    const confirmed = window.confirm(`Delete "${document.title}" from this workspace?`);
    if (!confirmed) {
      return;
    }

    setDeleteError(null);
    setDeletingDocumentId(document.document_id);
    try {
      await deleteDocument(token, document.document_id);
      await onRefresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        onAuthExpired();
        return;
      }
      setDeleteError(errorMessage(caught));
    } finally {
      setDeletingDocumentId(null);
    }
  }

  return (
    <section className="panel library-panel" aria-labelledby="documents-title">
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

      <div className="toolbar library-toolbar">
        <label className="search-field">
          <Search size={17} aria-hidden="true" />
          <input
            aria-label="Search documents"
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
      {deleteError ? <InlineAlert tone="error" message={deleteError} /> : null}
      {isLoading ? <LoadingRows /> : null}
      {!isLoading && filteredDocuments.length === 0 ? (
        <EmptyState
          icon={<FileText size={28} />}
          title="No documents found"
          detail="Upload evidence or adjust the current filters."
        />
      ) : null}
      {!isLoading && filteredDocuments.length > 0 ? (
        <>
          <div className="table-wrap library-table-wrap">
            <table className="library-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Country</th>
                  <th>Language</th>
                  <th>Status</th>
                  <th>Chunks</th>
                  <th>Created</th>
                  {isAdmin ? <th>Actions</th> : null}
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
                    {isAdmin ? (
                      <td>
                        <button
                          className="icon-text-button danger-action"
                          type="button"
                          onClick={() => void handleDelete(document)}
                          disabled={deletingDocumentId === document.document_id}
                          title="Delete document"
                        >
                          <Trash2 size={16} aria-hidden="true" />
                          {deletingDocumentId === document.document_id ? "Deleting..." : "Delete"}
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="library-footer">
            <span>
              Showing 1 to {visibleCount} of {totalCount} documents
            </span>
            <div className="pagination-controls" aria-label="Document pagination">
              <button className="icon-button pagination-button" type="button" disabled>
                <ChevronLeft size={18} aria-hidden="true" />
                <span className="sr-only">Previous page</span>
              </button>
              <button className="pagination-page active" type="button" aria-current="page">
                1
              </button>
              <button className="icon-button pagination-button" type="button" disabled>
                <ChevronRight size={18} aria-hidden="true" />
                <span className="sr-only">Next page</span>
              </button>
            </div>
          </div>
        </>
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
  const [country, setCountry] = useState("United Kingdom");
  const [documentId, setDocumentId] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const readyDocuments = documents.filter((document) => document.status === "ready");
  const canSubmit = question.trim().length >= 3 && !isSubmitting;
  const suggestionPrompts = [
    {
      icon: <Sparkles size={22} aria-hidden="true" />,
      label: "Summarise the evidence base",
    },
    {
      icon: <CircleHelp size={22} aria-hidden="true" />,
      label: "What are the main reimbursement barriers in the UK?",
    },
    {
      icon: <Scale size={22} aria-hidden="true" />,
      label: "Compare recommendations across uploaded documents",
    },
  ];

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
    <section className="chat-page" aria-labelledby="chat-title">
      <div className="chat-scope-toolbar" aria-label="Ask filters">
        <label className="scope-control">
          <Globe2 size={19} aria-hidden="true" />
          <select value={country} onChange={(event) => setCountry(event.target.value)}>
            <option value="">All countries</option>
            {COUNTRY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="scope-control readonly">
          <FileText size={19} aria-hidden="true" />
          <span>{readyDocuments.length} ready documents</span>
        </div>
        <label className="scope-control document-scope">
          <BookOpen size={19} aria-hidden="true" />
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
        <button
          className="icon-text-button"
          type="button"
          onClick={() => {
            setCountry("");
            setDocumentId("all");
          }}
        >
          <SlidersHorizontal size={18} aria-hidden="true" />
          Filters
        </button>
      </div>

      <div className="chat-main panel">
        <div className="message-stream" aria-live="polite">
          {messages.length === 0 ? (
            <div className="chat-empty-state">
              <div className="chat-empty-icon" aria-hidden="true">
                <MessageSquareText size={34} />
              </div>
              <h3 id="chat-title">Ask from uploaded evidence</h3>
              <p>Answers include confidence, limitations, and source snippets.</p>
              <div className="chat-separator" aria-hidden="true">
                <Sparkles size={16} />
              </div>
              <div className="suggestion-grid">
                {suggestionPrompts.map((suggestion) => (
                  <button
                    key={suggestion.label}
                    className="suggestion-card"
                    type="button"
                    onClick={() => setQuestion(suggestion.label)}
                  >
                    <span>{suggestion.icon}</span>
                    {suggestion.label}
                  </button>
                ))}
              </div>
            </div>
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
          <div className="ask-input-shell">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onPaste={(event) => {
                event.preventDefault();
                const pasted = normalisePastedQuestionText(event.clipboardData.getData("text"));
                const target = event.currentTarget;
                const start = target.selectionStart;
                const end = target.selectionEnd;
                setQuestion((current) => `${current.slice(0, start)}${pasted}${current.slice(end)}`);
              }}
              placeholder="Ask a market-access question"
              rows={2}
            />
            <div className="ask-tool-row">
              <div className="ask-tool-group">
                <button className="icon-button" type="button" disabled aria-label="Add evidence">
                  <Plus size={19} aria-hidden="true" />
                </button>
                <button className="icon-button" type="button" disabled aria-label="Attach file">
                  <Paperclip size={18} aria-hidden="true" />
                </button>
              </div>
              <div className="ask-tool-group">
                <button className="icon-button" type="button" disabled aria-label="Source guide">
                  <BookOpen size={18} aria-hidden="true" />
                </button>
                <button className="primary-button" type="submit" disabled={!canSubmit}>
                  <Send size={18} aria-hidden="true" />
                  {isSubmitting ? "Asking..." : "Ask"}
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </section>
  );
}

function AssistantMessage({ response }: { response: AskResponse }) {
  const [copied, setCopied] = useState(false);
  const [selectedSource, setSelectedSource] = useState<AnswerSource | null>(null);

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
        <p className="answer-text">
          {renderAnswer(response.answer, response.sources, setSelectedSource)}
        </p>
        {response.sources.length > 0 ? (
          <SourceReferenceChips sources={response.sources} onSelect={setSelectedSource} />
        ) : null}
        {response.uncertainty ? (
          <div className="uncertainty">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{response.uncertainty}</span>
          </div>
        ) : null}
        <p className="limitations">{response.limitations}</p>
        {copied ? <span className="copy-confirmation">Copied</span> : null}
      </div>
      {selectedSource ? (
        <SourceEvidenceDialog source={selectedSource} onClose={() => setSelectedSource(null)} />
      ) : null}
    </article>
  );
}

function SourceReferenceChips({
  sources,
  onSelect,
}: {
  sources: AnswerSource[];
  onSelect: (source: AnswerSource) => void;
}) {
  return (
    <div className="source-chip-row" aria-label="Answer references">
      <span>References</span>
      {sources.map((source) => (
        <button
          className="source-chip"
          key={`${source.document_id}-${source.source_id}`}
          type="button"
          onClick={() => onSelect(source)}
        >
          {source.source_id}
        </button>
      ))}
    </div>
  );
}

function SourceEvidenceDialog({
  source,
  onClose,
}: {
  source: AnswerSource;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="source-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="source-dialog-header">
          <div>
            <span className="source-dialog-label">{source.source_id}</span>
            <h3 id="source-dialog-title">{source.document_title}</h3>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close source evidence">
            <XCircle size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="source-dialog-meta">
          <span>{formatScore(source.relevance_score)}</span>
          <span>{source.country ?? "Unknown country"}</span>
          <span>{source.language ?? "Unknown language"}</span>
          {source.page_number && source.page_number > 0 ? <span>Page {source.page_number}</span> : null}
          {source.section_title ? <span>{source.section_title}</span> : null}
        </div>
        <div className="source-dialog-body">
          <p>{source.snippet}</p>
        </div>
        <div className="source-dialog-actions">
          <button className="icon-text-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </section>
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

function renderAnswer(
  answer: string,
  sources: AnswerSource[],
  onSourceClick: (source: AnswerSource) => void,
) {
  const sourceById = new Map(sources.map((source) => [source.source_id, source]));
  return answer.split(/(\[[^\]]+\])/g).map((part, index) => {
    const knownSourceIds = knownSourceIdsInCitation(part, sourceById);
    if (knownSourceIds.length === 0) {
      return <span key={`${part}-${index}`}>{part}</span>;
    }
    return (
      <span className="source-token-group" key={`${part}-${index}`}>
        [
        {knownSourceIds.map((sourceId, sourceIndex) => {
          const source = sourceById.get(sourceId);
          if (!source) {
            return null;
          }
          return (
            <span key={`${sourceId}-${index}`}>
              {sourceIndex > 0 ? ", " : null}
              <button
                className="source-token"
                type="button"
                onClick={() => onSourceClick(source)}
              >
                {sourceId}
              </button>
            </span>
          );
        })}
        ]
      </span>
    );
  });
}

function knownSourceIdsInCitation(
  text: string,
  sourceById: Map<string, AnswerSource>,
): string[] {
  return Array.from(sourceById.keys()).filter((sourceId) => {
    const pattern = new RegExp(`(^|[^A-Za-z0-9-])${escapeRegExp(sourceId)}([^A-Za-z0-9-]|$)`);
    return pattern.test(text);
  });
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function normalisePastedQuestionText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/([A-Za-z])%([A-Za-z])/g, "$1ti$2");
}

function makeId(): string {
  return crypto.randomUUID();
}
