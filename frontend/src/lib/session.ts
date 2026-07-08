import type { AuthSession } from "../types";

export const SESSION_STORAGE_KEY = "kintiga.auth.session";

export function readStoredSession(): AuthSession | null {
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

export function storeSession(session: AuthSession | null): void {
  if (!session) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}
