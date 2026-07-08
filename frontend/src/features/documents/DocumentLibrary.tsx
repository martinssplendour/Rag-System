import { ChevronLeft, ChevronRight, FileText, RefreshCw, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError, deleteDocument } from "../../api";
import { StatusBadge } from "../../components/Badges";
import { EmptyState } from "../../components/EmptyState";
import { InlineAlert } from "../../components/InlineAlert";
import { LoadingRows } from "../../components/LoadingRows";
import { errorMessage } from "../../lib/errors";
import { formatDate } from "../../lib/format";
import type { DocumentItem, DocumentStatus } from "../../types";

export function DocumentLibrary({
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
