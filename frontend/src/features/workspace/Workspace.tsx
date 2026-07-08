import { CheckCircle2, FolderOpen, MessageSquareText, ShieldCheck, Upload, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "../../components/EmptyState";
import { NavButton } from "../../components/NavButton";
import type { AuthSession } from "../../types";
import { EvidenceChat } from "../chat/EvidenceChat";
import { useChatSession } from "../chat/useChatSession";
import { DocumentLibrary } from "../documents/DocumentLibrary";
import { useDocuments } from "../documents/useDocuments";
import { UploadEvidence } from "../upload/UploadEvidence";
import { PageHeader } from "./PageHeader";
import type { View } from "./types";

export function Workspace({ session, onLogout }: { session: AuthSession; onLogout: () => void }) {
  const [view, setView] = useState<View>("chat");
  const { documents, isLoadingDocuments, documentError, refreshDocuments } = useDocuments(
    session.accessToken,
    onLogout,
  );
  const chat = useChatSession(session, onLogout);

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

        <div className="sidebar-status-card" aria-label="Documents status">
          <strong>Documents status</strong>
          <div className="sidebar-status-grid">
            <div>
              <span>
                <CheckCircle2 size={16} aria-hidden="true" />
                Ready
              </span>
              <strong className="status-count success">{readyCount}</strong>
            </div>
            <div>
              <span>
                <XCircle size={16} aria-hidden="true" />
                Failed
              </span>
              <strong className="status-count danger">{failedCount}</strong>
            </div>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <main className="workspace-content">
          <PageHeader view={view} session={session} onLogout={onLogout} />
          {view === "chat" ? (
            <EvidenceChat
              documents={documents}
              chat={chat}
            />
          ) : null}
          {view === "upload" && session.isAdmin ? (
            <UploadEvidence
              token={session.accessToken}
              onUploaded={async () => {
                await refreshDocuments();
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
