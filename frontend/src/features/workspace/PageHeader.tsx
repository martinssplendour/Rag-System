import { ChevronDown, FolderOpen, MessageSquareText, Upload, User } from "lucide-react";

import type { AuthSession } from "../../types";
import type { View } from "./types";
import { viewSubtitle, viewTitle } from "./types";

export function PageHeader({
  view,
  session,
  onLogout,
}: {
  view: View;
  session: AuthSession;
  onLogout: () => void;
}) {
  const Icon = view === "chat" ? MessageSquareText : view === "upload" ? Upload : FolderOpen;
  return (
    <header className="page-header">
      <div className="page-title-group">
        <span className="page-header-icon" aria-hidden="true">
          <Icon size={28} />
        </span>
        <div>
          <h1>{viewTitle(view)}</h1>
          <p>{viewSubtitle(view)}</p>
        </div>
      </div>
      <button
        className="account-card"
        type="button"
        onClick={onLogout}
        aria-label={`Logout ${session.email}`}
      >
        <User size={18} aria-hidden="true" />
        <span>{session.email}</span>
        <span className={`role-badge ${session.isAdmin ? "admin" : "standard"}`}>
          {session.isAdmin ? "Admin" : "User"}
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </button>
    </header>
  );
}
