import { useState } from "react";

import { AuthScreen } from "./features/auth/AuthScreen";
import { Workspace } from "./features/workspace/Workspace";
import { clearChatHistory } from "./features/chat/history";
import { readStoredSession, storeSession } from "./lib/session";
import type { AuthSession } from "./types";

export function App() {
  const [session, setSession] = useState<AuthSession | null>(() => readStoredSession());

  const handleAuthenticated = (nextSession: AuthSession) => {
    storeSession(nextSession);
    setSession(nextSession);
  };

  const handleLogout = () => {
    if (session) {
      clearChatHistory(session);
    }
    storeSession(null);
    setSession(null);
  };

  if (!session) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }

  return <Workspace session={session} onLogout={handleLogout} />;
}
